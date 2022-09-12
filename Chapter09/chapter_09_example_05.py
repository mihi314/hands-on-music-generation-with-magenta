"""
This example shows a basic Drums RNN generation with a
looping synthesizer playback, generating a new sequence at each loop,
using a MIDI hub to send the sequence to an external device.

VERSION: Magenta 2.1.2
"""
import argparse
import os
import time
from decimal import Decimal
from datetime import datetime

import mido
import tensorflow as tf
from magenta.common import concurrency
from magenta.interfaces.midi.midi_hub import MidiHub
from magenta.interfaces.midi.midi_interaction import adjust_sequence_times
from magenta.models.drums_rnn import drums_rnn_sequence_generator
from magenta.models.shared import sequence_generator_bundle
from note_seq import constants
from note_seq import midi_io
from note_seq import trim_note_sequence
from note_seq import notebook_utils
from note_seq.protobuf import generator_pb2
from note_seq.protobuf import music_pb2
from visual_midi import Plotter

parser = argparse.ArgumentParser()
parser.add_argument("--midi_port", type=str, default="FLUID Synth")
args = parser.parse_args()


def generate(unused_argv):
  # Downloads the bundle from the magenta website
  notebook_utils.download_bundle("drum_kit_rnn.mag", "bundles")
  bundle = sequence_generator_bundle.read_bundle_file(
    os.path.join("bundles", "drum_kit_rnn.mag"))

  # Initialize the generator "drum_kit"
  generator_map = drums_rnn_sequence_generator.get_generator_map()
  generator = generator_map["drum_kit"](checkpoint=None, bundle=bundle)
  generator.initialize()

  # Define constants
  qpm = 120
  num_bars = 3
  seconds_per_step = 60.0 / qpm / generator.steps_per_quarter
  num_steps_per_bar = constants.DEFAULT_STEPS_PER_BAR
  seconds_per_bar = num_steps_per_bar * seconds_per_step

  # Use a priming sequence
  primer_sequence = midi_io.midi_file_to_note_sequence(
    os.path.join("primers", "Jazz_Drum_Basic_1_bar.mid"))
  primer_start_time = 0
  primer_end_time = primer_start_time + seconds_per_bar

  # Calculates the generation start and end time
  generation_start_time = primer_end_time
  generation_end_time = generation_start_time + (seconds_per_bar * num_bars)
  generator_options = generator_pb2.GeneratorOptions()
  generator_options.args['temperature'].float_value = 1.1
  generator_options.generate_sections.add(
    start_time=generation_start_time,
    end_time=generation_end_time)

  # Generates on primer sequence
  sequence = generator.generate(primer_sequence, generator_options)

  # Outputs the plot
  # os.makedirs("output", exist_ok=True)
  # plot_file = os.path.join("output", "out.html")
  # pretty_midi = midi_io.note_sequence_to_pretty_midi(sequence)
  # plotter = Plotter(live_reload=True)
  # plotter.show(pretty_midi, plot_file)
  # print(f"Generated plot file: {os.path.abspath(plot_file)}")

  # We find the proper input port for the software synth
  # (which is the output port for Magenta)
  output_ports = [name for name in mido.get_output_names()
                  if args.midi_port in name]
  if not output_ports:
    raise Exception(f"Cannot find proper output ports in: "
                    f"{mido.get_output_names()}")
  print(f"Playing generated MIDI in output port names: {output_ports}")

  # Start a new MIDI hub on that port (output only)
  midi_hub = MidiHub(input_midi_ports=[],
                     output_midi_ports=output_ports,
                     texture_type=None)

  # Start on a empty sequence, allowing the update of the
  # sequence for later.
  empty_sequence = music_pb2.NoteSequence()
  player = midi_hub.start_playback(empty_sequence,
                                   allow_updates=True)
  player._channel = 9

  # We want a period in seconds of 4 bars
  period = Decimal(240) / qpm
  period = period * (num_bars + 1)
  sleeper = concurrency.Sleeper()
  while True:
    try:
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
      sequence_adjusted = adjust_sequence_times(sequence_adjusted,
                                                float(tick_time))
      player.update_sequence(sequence_adjusted,
                             start_time=float(tick_time))

      # Generate a new sequence based on the previous sequence
      generator_options = generator_pb2.GeneratorOptions()
      generator_options.args['temperature'].float_value = 1.3
      generation_start_time = float(period)
      generation_end_time = 2 * float(period)
      generator_options.generate_sections.add(
        start_time=generation_start_time,
        end_time=generation_end_time)
      sequence = generator.generate(sequence, generator_options)
      sequence = trim_note_sequence(sequence,
                                    generation_start_time,
                                    generation_end_time)
      sequence = adjust_sequence_times(sequence, -float(period))

      # Sleep until the next tick time
      sleeper.sleep_until(float(tick_time_next))
    except KeyboardInterrupt:
      print(f"Stopping")
      return 0


def print_sequence_info(sequence):
  start = sequence.notes[0].start_time
  end = sequence.notes[-1].end_time
  if (start > 100000):
    start = datetime.fromtimestamp(start)
    end = datetime.fromtimestamp(end)
  print(f"sequence start: {start}, end: {end}")


if __name__ == "__main__":
  tf.compat.v1.disable_v2_behavior()
  tf.compat.v1.app.run(generate)
