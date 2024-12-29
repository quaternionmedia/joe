# Joe

Joe (named after Joseph Fourier) is a project that aims to visualize music in real(ish) time and to perform further analysis on it, including outputing midi sheet music.

There are a few main components to this project - a p5.js/mithril.js frontend, a python backend, and some ipython notebooks for analysis and IO. These are intended to cooperate, but stay useful on their own too. Maybe someday these will be proper submodules (PRs welcome).

## Setup

### Python backend/logic
We're using `pdm` to get things going on the back end. 

Assuming you've got the proper binary installed locally (`pip install pdm`), you can run `pdm install` to get things started. This will get a venv set up for you too.

You can then run `pdm run python main.py` to run analysis on the audio files in the `Data/Audio` directory.

The `main.py` script will create a `Process_Data.json` file in the `Output` directory, which will contain the data used for each run. This is where `Audio` classes for each file are created, and `Midi` classes are created for each `Chroma` class. Thresholds and processing parameters are set here.

### P5/mithril front end
`npx vite` should get the party started
(maybe `npm i vite` if you don't have it installed)