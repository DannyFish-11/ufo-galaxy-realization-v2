# Data Processing Scripts

```
# Setup environment

cd AgentCPM-GUI/eval/eval_data
conda create -n process_data python=3.11
conda activate process_data
pip install -r requirements.txt

mkdir tmp && cd tmp
git clone https://github.com/deepmind/android_env/
cd android_env; pip install .
```

## Android Control

Download [Android Control](https://github.com/google-research/google-research/tree/master/android_control) and save at ``AgentCPM-GUI/eval/eval_data/tmp/android_control``

```
cd AgentCPM-GUI/eval/eval_data
python process_ac.py
ln -s android_control_test android_control_high_test
ln -s android_control_test android_control_low_test
```

## CAGUI

```
cd AgentCPM-GUI/eval/eval_data
mkdir chinese_app_test && cd chinese_app_test
huggingface-cli download openbmb/CAGUI --repo-type dataset --include "CAGUI_agent/**" --local-dir ./ --local-dir-use-symlinks False --resume-download
mv CAGUI_agent test
```

## aitz

Download [aitz](https://github.com/IMNearth/CoAT) and save at ``AgentCPM-GUI/eval/eval_data/tmp/android_in_the_zoo``

```
cd AgentCPM-GUI/eval/eval_data
mv tmp/android_in_the_zoo ./aitz_test
python process_aitz.py
```

## gui-odyssey

Download [GUI-Odyssey](https://github.com/OpenGVLab/GUI-Odyssey?tab=readme-ov-file) and save at ``AgentCPM-GUI/eval/eval_data/tmp/GUI-Odyssey``. Copy [preprocessing.py](https://github.com/OpenGVLab/GUI-Odyssey/blob/master/data/preprocessing.py) and [format_converter.py](https://github.com/OpenGVLab/GUI-Odyssey/blob/master/data/format_converter.py) from the GUI-Odyssey repo to ``AgentCPM-GUI/eval/eval_data/tmp/GUI-Odyssey``

```
cd AgentCPM-GUI/eval/eval_data/tmp/GUI-Odyssey
python preprocessing.py
python format_converter.py
python ../../process_odyssey.py
```
