import time
import math
from dataclasses import dataclass
import os
from decimal import Decimal
from datetime import datetime

import mido
import tensorflow as tf
from magenta.common import concurrency
from magenta.interfaces.midi.midi_hub import MidiHub
from magenta.interfaces.midi.midi_interaction import adjust_sequence_times
from magenta.models.drums_rnn import drums_rnn_sequence_generator
from magenta.models.performance_rnn import performance_sequence_generator
from magenta.models.shared import sequence_generator_bundle
from note_seq import constants
from note_seq import midi_io
from note_seq import trim_note_sequence
from note_seq import notebook_utils
from note_seq.protobuf import generator_pb2
from note_seq.protobuf import music_pb2


@dataclass
class Parameters:
    tempo: float = 10
    temperature: float = 1.3
    notes_per_second: int = 5


midi_port = "FLUID Synth"

pitch_class_histogram = "[1, 0, 1, 0, 1, 2, 0, 1, 0, 1, 0, 1]"


def generate_and_play(params: Parameters):
    # Downloads the bundle from the magenta website
    notebook_utils.download_bundle("multiconditioned_performance_with_dynamics.mag", "bundles")
    bundle = sequence_generator_bundle.read_bundle_file(
        os.path.join("bundles", "multiconditioned_performance_with_dynamics.mag")
    )

    # Initialize the generator "drum_kit"
    generator_map = performance_sequence_generator.get_generator_map()
    generator = generator_map["multiconditioned_performance_with_dynamics"](checkpoint=None, bundle=bundle)
    generator.initialize()

    # Define constants
    qpm = 120
    num_bars = 3
    seconds_per_step = 60.0 / qpm / getattr(generator, "steps_per_quarter", 4)
    num_steps_per_bar = constants.DEFAULT_STEPS_PER_BAR
    seconds_per_bar = num_steps_per_bar * seconds_per_step

    # Use a priming sequence
    primer_sequence = midi_io.midi_file_to_note_sequence(os.path.join("primers", "Fur_Elisa_Beethoveen_Polyphonic.mid"))
    # TODO: This is just a hack for now to make the primer + first generated sequence be 4 bars long. All the time 
    # stuff here needs to be properly refactored
    primer_sequence = trim_note_sequence(primer_sequence, 0, seconds_per_bar * 1)

    # Calculates the primer sequence length in steps and time by taking the
    # total time (which is the end of the last note) and finding the next step
    # start time.
    primer_sequence_length_steps = math.ceil(primer_sequence.total_time / seconds_per_step)
    primer_sequence_length_time = primer_sequence_length_steps * seconds_per_step

    # Calculates the start and the end of the primer sequence.
    # We add a negative delta to the end, because if we don't some generators
    # won't start the generation right at the beginning of the bar, they will
    # start at the next step, meaning we'll have a small gap between the primer
    # and the generated sequence.
    primer_end_adjust = 0.00001 if primer_sequence_length_time > 0 else 0
    primer_end_adjust = 0
    primer_start_time = 0
    primer_end_time = primer_start_time + primer_sequence_length_time - primer_end_adjust

    # Calculates the generate start and end time, the start time will contain
    # the previously added negative delta from the primer end time.
    # We remove the generation end time delta to end the generation
    # on the last bar.
    generation_start_time = primer_end_time
    generation_end_time = generation_start_time + primer_end_adjust + seconds_per_bar * num_bars

    # Showtime
    print(f"Primer time: [{primer_start_time}, {primer_end_time}]")
    print(f"Generation time: [{generation_start_time}, {generation_end_time}]")

    # Pass the given parameters, the generator options are common for all models,
    # except for condition_on_primer and no_inject_primer_during_generation
    # which are specific to polyphonic models
    generator_options = generator_pb2.GeneratorOptions()
    generator_options.args["temperature"].float_value = 1.1
    generator_options.args["pitch_class_histogram"].string_value = pitch_class_histogram
    generator_options.args['notes_per_second'].string_value = str(params.notes_per_second)
    # generator_options.args["beam_size"].int_value = beam_size
    # generator_options.args["branch_factor"].int_value = branch_factor
    # generator_options.args["steps_per_iteration"].int_value = steps_per_iteration
    # if notes_per_second:
    #     generator_options.args["notes_per_second"].string_value = notes_per_second
    # if pitch_class_histogram:
    #     generator_options.args["pitch_class_histogram"].string_value = pitch_class_histogram
    generator_options.generate_sections.add(start_time=generation_start_time, end_time=generation_end_time)


    # Generates on primer sequence
    sequence = generator.generate(primer_sequence, generator_options)

    # We find the proper input port for the software synth
    # (which is the output port for Magenta)
    output_ports = [name for name in mido.get_output_names() if midi_port in name]
    if not output_ports:
        raise Exception(f"Cannot find proper output ports in: " f"{mido.get_output_names()}")

    # Start a new MIDI hub on that port (output only)
    midi_hub = MidiHub(input_midi_ports=[], output_midi_ports=output_ports, texture_type=None)

    # Start on a empty sequence, allowing the update of the sequence for later.
    empty_sequence = music_pb2.NoteSequence()
    player = midi_hub.start_playback(empty_sequence, allow_updates=True)
    player._channel = 0

    # We want a period in seconds of 4 bars
    period = Decimal(4 * 60) / qpm
    period = period * (num_bars + 1)
    sleeper = concurrency.Sleeper()
    while True:
        # We get the next tick time by using the period
        # to find the absolute tick number.
        now = Decimal(time.time())
        tick_number = int(now // period)
        tick_number_next = tick_number + 1
        tick_time = tick_number * period
        tick_time_next = tick_number_next * period

        # Update the player time to the current tick time
        sequence_adjusted = music_pb2.NoteSequence()
        sequence_adjusted.CopyFrom(sequence)
        sequence_adjusted = adjust_sequence_times(sequence_adjusted, float(tick_time))
        player.update_sequence(sequence_adjusted, start_time=float(tick_time))

        print(params)

        # Generate a new sequence based on the previous sequence
        generator_options = generator_pb2.GeneratorOptions()
        generator_options.args["temperature"].float_value = params.temperature
        generator_options.args["pitch_class_histogram"].string_value = pitch_class_histogram
        generator_options.args['notes_per_second'].string_value = str(params.notes_per_second)
        generation_start_time = float(period)
        generation_end_time = 2 * float(period)
        generator_options.generate_sections.add(start_time=generation_start_time, end_time=generation_end_time)
        sequence = generator.generate(sequence, generator_options)
        sequence = trim_note_sequence(sequence, generation_start_time, generation_end_time)
        sequence = adjust_sequence_times(sequence, -float(period))

        # Sleep until the next tick time
        sleeper.sleep_until(float(tick_time_next))
