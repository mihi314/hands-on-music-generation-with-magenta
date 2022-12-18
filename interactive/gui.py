import PySimpleGUI as sg
import threading

from generator import Parameters, generate_and_play


# sg.theme('BluePurple')

defaults = Parameters()
params = Parameters()


NODES_PER_S = "-NOTES_PER_SECOND-"
TEMPERATURE = "-TEMPERATURE-"

layout = [
    [],
    [
        sg.Text("Notes per second"),
        sg.Slider(
            range=(1, 50), orientation="h", size=(20, 20), default_value=defaults.notes_per_second, enable_events=True, key=NODES_PER_S
        ),
    ],
    [
        sg.Text("Temperature"),
        sg.Slider(
            range=(0.1, 10),
            resolution=0.1,
            orientation="h",
            size=(20, 20),
            default_value=defaults.temperature,
            enable_events=True,
            key=TEMPERATURE,
        ),
    ],
    [sg.Button("Exit")],
]

window = sg.Window("magenta", layout)

threading.Thread(target=lambda: generate_and_play(params), args=(), daemon=True).start()

while True:
    event, values = window.read()
    # print(event, values)
    if event == sg.WIN_CLOSED or event == "Exit":
        break
    if event == NODES_PER_S:
        params.notes_per_second = values[NODES_PER_S]
    if event == TEMPERATURE:
        params.temperature = values[TEMPERATURE]

window.close()

# can generate in a separate thread and still handle the event loop? probably?
# how to communicate? queue? just globals? queue?
