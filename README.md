# bbl2wav.py

This script converts `GYRO_SCALED` gyro data from Betaflight blackbox logs (`.bbl` files) into `.wav` audio files.

Sampled at 4kHz:

[demo.webm](https://github.com/vmzhivetyev/bbl2wav/assets/22922662/64972f7e-2128-4add-b36c-cde2f2c08f52)

## Installation

```bash
# Clone
git clone https://github.com/vmzhivetyev/bbl2wav
cd bbl2wav

# venv
python3 -m venv venv
source venv/bin/activate

# install reqs
pip3 install -r requirements.txt
```

## Usage

Record a blackbox log file with debug_mode set to GYRO_SCALED so unfiltered gyro data is recorded. 

> [!IMPORTANT]
> Use blackbox sample rate of 2000Hz or higher.

Then do:

```bash
python3 bbl2wav.py <btfl_001.bbl>
```

Replace `<btfl_001.bbl>` with the path to the `.bbl` file you want to convert.

## Output

The script generates `.wav` files containing the audio file by derictly converting gyro data from the log into wav file without any modifications. 

Each axis (`roll`, `pitch`, `yaw`) of the gyro data is converted into a separate audio file. The output files are named in the following format:

```
<original_filename>_<log_index>_<axis>.wav
```

For example, if the input `.bbl` file is named `btfl_001.bbl` and it contains multiple logs (you armed mutliple times), the generated files might be named as follows:

- `btfl_001_1_roll.wav`
- `btfl_001_1_pitch.wav`
- `btfl_001_1_yaw.wav`
- `btfl_001_2_roll.wav`
- `btfl_001_2_pitch.wav`
- `btfl_001_2_yaw.wav`
- and so on...
