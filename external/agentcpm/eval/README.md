# Evaluation Scripts

## Grounding Benchmark

| Model                   | Fun2Point | Text2Point | Bbox2Text | Average |
|-------------------------|-----------|------------|-----------|--------|
| **AgentCPM-GUI-8B**     | **79.1**  | **76.5**   | **58.2**  |**71.3**|
| Qwen2.5-VL-7B           | 59.8      | 59.3       | <ins>50.0</ins>      | <ins>56.4</ins>   |
| Intern2.5-VL-8B         | 17.2      | 24.2       | 45.9      | 29.1   |
| Intern2.5-VL-26B        | 14.8      | 16.6       | 36.3      | 22.6   |
| OS-Genesis-7B	        | 8.3	      | 5.8	       | 4.0       | 6.0    |
| UI-TARS-7B              | 56.8      | <ins>66.7</ins>       | 1.4       | 41.6   |
| OS-Atlas-7B             | 53.6      | 60.7       | 0.4       | 38.2   |
| Aguvis-7B	              | <ins>60.8</ins>      | **76.5**   | 0.2       | 45.8   |
| GPT-4o                  | 22.1      | 19.9       | 14.3      | 18.8   |
| GPT-4o with Grounding   | 44.3      | 44.0       | 14.3      | 44.2   |

---

## Agent Benchmark

| Dataset                   | Android Control-Low TM | Android Control-Low EM | Android Control-High TM | Android Control-High EM | GUI-Odyssey TM  | GUI-Odyssey EM  | AITZ TM         | AITZ EM         | Chinese APP (CAGUI) TM  | Chinese APP (CAGUI) EM  |
| ------------------------- | ---------------------- | ---------------------- | ----------------------- | ----------------------- | --------------- | --------------- | --------------- | --------------- | --------------- | --------------- |
| **AgentCPM-GUI-8B** | <ins>94.39</ins> | <ins>90.20</ins> | <ins>77.70</ins> | <ins>69.17</ins> | **90.85** | **74.96** | **85.71** | **76.38** | **96.86** | **91.28** |
| Qwen2.5-VL-7B             | 94.14                  | 84.96                  | 75.10                   | 62.90                   | 59.54           | 46.28           | 78.41           | 54.61           | 74.18            | 55.16           |
| UI-TARS-7B                | **95.24**                  | **91.79**                  | **81.63**                   | **74.43**                   | 86.06           | 67.90           | <ins>80.42</ins>           | <ins>65.77</ins>           | <ins>88.62</ins>           | <ins>70.26</ins>           |
| OS-Genesis-7B             | 90.74                  | 74.22                  | 65.92                   | 44.43                   | 11.67           | 3.63            | 19.98           | 8.45            | 38.10           | 14.50           |
| OS-Atlas-7B               | 73.03                  | 67.25                  | 70.36                   | 56.53                   | 91.83*            | 76.76*           | 74.13           | 58.45           | 81.53           | 55.89           |
| Aguvis-7B                 | 93.85                  | 89.40                  | 65.56                   | 54.18                   | 26.71           | 13.54           | 35.71           | 18.99           | 67.43           | 38.20           |
| OdysseyAgent-7B           | 65.10                  | 39.16                  | 58.80                   | 32.74                   | <ins>90.83</ins>           | <ins>73.67</ins>           | 59.17           | 31.60           | 67.56           | 25.44           |
| GPT-4o                    | -                      | 19.49                  | -                       | 20.80                   | -               | 20.39           | 70.00           | 35.30           | 3.67            | 3.67            |
| Gemini 2.0                | -                      | 28.50                  | -                       | 60.20                   | -               | 3.27            | -               | -               | -               | -               |
| Claude                    | -                      | 19.40                  | -                       | 12.50                   | 60.90           | -               | -               | -               | -               | -               |

> \*Different train/test splits

## Data Preparation

Follow [eval_data/readme.md](eval_data/readme.md) to setup eval datasets.

---

## AgentCPM-GUI-8B

### Inference

```bash
# aitz_test
python run_predict_minicpm.py --model_path ../model/AgentCPM-GUI --output_dir ./eval_results/AgentCPM-GUI/aitz_test --data_name aitz_test

# gui_odyssey_test
python run_predict_minicpm.py --model_path ../model/AgentCPM-GUI --output_dir ./eval_results/AgentCPM-GUI/gui_odyssey_test --data_name gui_odyssey_test

# chinese_app_test
python run_predict_minicpm.py --model_path ../model/AgentCPM-GUI --output_dir ./eval_results/AgentCPM-GUI/chinese_app_test --data_name chinese_app_test

# android_control_high_test
python run_predict_minicpm.py --model_path ../model/AgentCPM-GUI --output_dir ./eval_results/AgentCPM-GUI/android_control_high_test --data_name android_control_high_test

# android_control_low_test
python run_predict_minicpm.py --model_path ../model/AgentCPM-GUI --output_dir ./eval_results/AgentCPM-GUI/android_control_low_test --data_name android_control_low_test
```

### Eval

```bash
# aitz_test
python run_eval_agent.py --input_path ./eval_results/AgentCPM-GUI/aitz_test/all.jsonl --output_dir ./eval_results/AgentCPM-GUI/aitz_test/results --data_name aitz_test

# gui_odyssey_test
python run_eval_agent.py --input_path ./eval_results/AgentCPM-GUI/gui_odyssey_test/all.jsonl --output_dir ./eval_results/AgentCPM-GUI/gui_odyssey_test/results --data_name gui_odyssey_test

# chinese_app_test
python run_eval_agent.py --input_path ./eval_results/AgentCPM-GUI/chinese_app_test/all.jsonl --output_dir ./eval_results/AgentCPM-GUI/chinese_app_test/results --data_name chinese_app_test

# android_control_high_test
python run_eval_agent.py --input_path ./eval_results/AgentCPM-GUI/android_control_high_test/all.jsonl --output_dir ./eval_results/AgentCPM-GUI/android_control_high_test/results --data_name android_control_high_test --eval_android_control

# android_control_low_test
python run_eval_agent.py --input_path ./eval_results/AgentCPM-GUI/android_control_low_test/all.jsonl --output_dir ./eval_results/AgentCPM-GUI/android_control_low_test/results --data_name android_control_low_test --eval_android_control
```

---

## Qwen2.5-VL-7B

### Inference

```bash
# aitz_test
python run_predict_qwen2_5VL.py --model_path ../model/Qwen2.5-VL-7B-Instruct --output_dir ./eval_results/Qwen2.5-VL-7B-Instruct/aitz_test --data_name aitz_test

# gui_odyssey_test
python run_predict_qwen2_5VL.py --model_path ../model/Qwen2.5-VL-7B-Instruct --output_dir ./eval_results/Qwen2.5-VL-7B-Instruct/gui_odyssey_test --data_name gui_odyssey_test

# chinese_app_test
python run_predict_qwen2_5VL.py --model_path ../model/Qwen2.5-VL-7B-Instruct --output_dir ./eval_results/Qwen2.5-VL-7B-Instruct/chinese_app_test --data_name chinese_app_test

# android_control_high_test
python run_predict_qwen2_5VL.py --model_path ../model/Qwen2.5-VL-7B-Instruct --output_dir ./eval_results/Qwen2.5-VL-7B-Instruct/android_control_high_test --data_name android_control_high_test

# android_control_low_test
python run_predict_qwen2_5VL.py --model_path ../model/Qwen2.5-VL-7B-Instruct --output_dir ./eval_results/Qwen2.5-VL-7B-Instruct/android_control_low_test --data_name android_control_low_test
```

### Eval

```bash
# aitz_test
python run_eval_agent.py --input_path ./eval_results/Qwen2.5-VL-7B-Instruct/aitz_test/all.jsonl --output_dir ./eval_results/Qwen2.5-VL-7B-Instruct/aitz_test/results --data_name aitz_test

# gui_odyssey_test
python run_eval_agent.py --input_path ./eval_results/Qwen2.5-VL-7B-Instruct/gui_odyssey_test/all.jsonl --output_dir ./eval_results/Qwen2.5-VL-7B-Instruct/gui_odyssey_test/results --data_name gui_odyssey_test

# chinese_app_test
python run_eval_agent.py --input_path ./eval_results/Qwen2.5-VL-7B-Instruct/chinese_app_test/all.jsonl --output_dir ./eval_results/Qwen2.5-VL-7B-Instruct/chinese_app_test/results --data_name chinese_app_test

# android_control_high_test
python run_eval_agent.py --input_path ./eval_results/Qwen2.5-VL-7B-Instruct/android_control_high_test/all.jsonl --output_dir ./eval_results/Qwen2.5-VL-7B-Instruct/android_control_high_test/results --data_name android_control_high_test --eval_android_control

# android_control_low_test
python run_eval_agent.py --input_path ./eval_results/Qwen2.5-VL-7B-Instruct/android_control_low_test/all.jsonl --output_dir ./eval_results/Qwen2.5-VL-7B-Instruct/android_control_low_test/results --data_name android_control_low_test --eval_android_control
```

---

## UI-TARS-7B-SFT

### Inference

```bash
# aitz_test
python run_predict_ui_tars.py --model_path ../model/UI-TARS-7B-SFT --output_dir ./eval_results/UI-TARS-7B-SFT/aitz_test --data_name aitz_test

# gui_odyssey_test
python run_predict_ui_tars.py --model_path ../model/UI-TARS-7B-SFT --output_dir ./eval_results/UI-TARS-7B-SFT/gui_odyssey_test --data_name gui_odyssey_test

# chinese_app_test
python run_predict_ui_tars.py --model_path ../model/UI-TARS-7B-SFT --output_dir ./eval_results/UI-TARS-7B-SFT/chinese_app_test --data_name chinese_app_test

# android_control_high_test
python run_predict_ui_tars.py --model_path ../model/UI-TARS-7B-SFT --output_dir ./eval_results/UI-TARS-7B-SFT/android_control_high_test --data_name android_control_high_test

# android_control_low_test
python run_predict_ui_tars.py --model_path ../model/UI-TARS-7B-SFT --output_dir ./eval_results/UI-TARS-7B-SFT/android_control_low_test --data_name android_control_low_test
```

### Eval

```bash
# aitz_test
python run_eval_agent.py --input_path ./eval_results/UI-TARS-7B-SFT/aitz_test/all.jsonl --output_dir ./eval_results/UI-TARS-7B-SFT/aitz_test/results --data_name aitz_test

# gui_odyssey_test
python run_eval_agent.py --input_path ./eval_results/UI-TARS-7B-SFT/gui_odyssey_test/all.jsonl --output_dir ./eval_results/UI-TARS-7B-SFT/gui_odyssey_test/results --data_name gui_odyssey_test

# chinese_app_test
python run_eval_agent.py --input_path ./eval_results/UI-TARS-7B-SFT/chinese_app_test/all.jsonl --output_dir ./eval_results/UI-TARS-7B-SFT/chinese_app_test/results --data_name chinese_app_test

# android_control_high_test
python run_eval_agent.py --input_path ./eval_results/UI-TARS-7B-SFT/android_control_high_test/all.jsonl --output_dir ./eval_results/UI-TARS-7B-SFT/android_control_high_test/results --data_name android_control_high_test --eval_android_control

# android_control_low_test
python run_eval_agent.py --input_path ./eval_results/UI-TARS-7B-SFT/android_control_low_test/all.jsonl --output_dir ./eval_results/UI-TARS-7B-SFT/android_control_low_test/results --data_name android_control_low_test --eval_android_control
```

---

## OS-Genesis-7B-AC

### Inference

```bash
# aitz_test
python run_predict_os_gensis.py --model_path ../model/OS-Genesis-7B-AC --output_dir ./eval_results/OS-Genesis-7B-AC/aitz_test --data_name aitz_test

# gui_odyssey_test
python run_predict_os_gensis.py --model_path ../model/OS-Genesis-7B-AC --output_dir ./eval_results/OS-Genesis-7B-AC/gui_odyssey_test --data_name gui_odyssey_test

# chinese_app_test
python run_predict_os_gensis.py --model_path ../model/OS-Genesis-7B-AC --output_dir ./eval_results/OS-Genesis-7B-AC/chinese_app_test --data_name chinese_app_test

# android_control_high_test
python run_predict_os_gensis.py --model_path ../model/OS-Genesis-7B-AC --output_dir ./eval_results/OS-Genesis-7B-AC/android_control_high_test --data_name android_control_high_test

# android_control_low_test
python run_predict_os_gensis.py --model_path ../model/OS-Genesis-7B-AC --output_dir ./eval_results/OS-Genesis-7B-AC/android_control_low_test --data_name android_control_low_test
```

### Eval

```bash
# aitz_test
python run_eval_agent.py --input_path ./eval_results/OS-Genesis-7B-AC/aitz_test/all.jsonl --output_dir ./eval_results/OS-Genesis-7B-AC/aitz_test/results --data_name aitz_test

# gui_odyssey_test
python run_eval_agent.py --input_path ./eval_results/OS-Genesis-7B-AC/gui_odyssey_test/all.jsonl --output_dir ./eval_results/OS-Genesis-7B-AC/gui_odyssey_test/results --data_name gui_odyssey_test

# chinese_app_test
python run_eval_agent.py --input_path ./eval_results/OS-Genesis-7B-AC/chinese_app_test/all.jsonl --output_dir ./eval_results/OS-Genesis-7B-AC/chinese_app_test/results --data_name chinese_app_test

# android_control_high_test
python run_eval_agent.py --input_path ./eval_results/OS-Genesis-7B-AC/android_control_high_test/all.jsonl --output_dir ./eval_results/OS-Genesis-7B-AC/android_control_high_test/results --data_name android_control_high_test --eval_android_control

# android_control_low_test
python run_eval_agent.py --input_path ./eval_results/OS-Genesis-7B-AC/android_control_low_test/all.jsonl --output_dir ./eval_results/OS-Genesis-7B-AC/android_control_low_test/results --data_name android_control_low_test --eval_android_control
```

---

## OS-Atlas-Pro-7B

### Inference

```bash
# aitz_test
python run_predict_os_atlas.py --model_path ../model/OS-Atlas-Pro-7B --output_dir ./eval_results/OS-Atlas-Pro-7B/aitz_test --data_name aitz_test

# gui_odyssey_test
python run_predict_os_atlas.py --model_path ../model/OS-Atlas-Pro-7B --output_dir ./eval_results/OS-Atlas-Pro-7B/gui_odyssey_test --data_name gui_odyssey_test

# chinese_app_test
python run_predict_os_atlas.py --model_path ../model/OS-Atlas-Pro-7B --output_dir ./eval_results/OS-Atlas-Pro-7B/chinese_app_test --data_name chinese_app_test

# android_control_high_test
python run_predict_os_atlas.py --model_path ../model/OS-Atlas-Pro-7B --output_dir ./eval_results/OS-Atlas-Pro-7B/android_control_high_test --data_name android_control_high_test

# android_control_low_test
python run_predict_os_atlas.py --model_path ../model/OS-Atlas-Pro-7B --output_dir ./eval_results/OS-Atlas-Pro-7B/android_control_low_test --data_name android_control_low_test
```

### Eval

```bash
# aitz_test
python run_eval_agent.py --input_path ./eval_results/OS-Atlas-Pro-7B/aitz_test/all.jsonl --output_dir ./eval_results/OS-Atlas-Pro-7B/aitz_test/results --data_name aitz_test

# gui_odyssey_test
python run_eval_agent.py --input_path ./eval_results/OS-Atlas-Pro-7B/gui_odyssey_test/all.jsonl --output_dir ./eval_results/OS-Atlas-Pro-7B/gui_odyssey_test/results --data_name gui_odyssey_test

# chinese_app_test
python run_eval_agent.py --input_path ./eval_results/OS-Atlas-Pro-7B/chinese_app_test/all.jsonl --output_dir ./eval_results/OS-Atlas-Pro-7B/chinese_app_test/results --data_name chinese_app_test

# android_control_high_test
python run_eval_agent.py --input_path ./eval_results/OS-Atlas-Pro-7B/android_control_high_test/all.jsonl --output_dir ./eval_results/OS-Atlas-Pro-7B/android_control_high_test/results --data_name android_control_high_test --eval_android_control

# android_control_low_test
python run_eval_agent.py --input_path ./eval_results/OS-Atlas-Pro-7B/android_control_low_test/all.jsonl --output_dir ./eval_results/OS-Atlas-Pro-7B/android_control_low_test/results --data_name android_control_low_test --eval_android_control
```

---

## Aguvis-7B-720P

### Inference

```bash
# aitz_test

python run_predict_aguvis.py  --model_path ../model/aguvis --output_dir ./eval_results/aguvis/aitz_test --data_name aitz_test

# gui_odyssey_test
python run_predict_aguvis.py --model_path ../model/aguvis --output_dir ./eval_results/aguvis/gui_odyssey_test --data_name gui_odyssey_test

# chinese_app_test
python run_predict_aguvis.py  --model_path ../model/aguvis --output_dir ./eval_results/aguvis/chinese_app_test --data_name chinese_app_test

# android_control_high_test
python run_predict_aguvis.py  --model_path ../model/aguvis --output_dir ./eval_results/aguvis/android_control_high_test --data_name android_control_high_test

# android_control_low_test
python run_predict_aguvis.py  --model_path ../model/aguvis --output_dir ./eval_results/aguvis/android_control_low_test --data_name android_control_low_test
```
Additional params include: `--device`, `--temperature`, `--max_new_tokens`, `--mode`, see the code for more details.

### Eval
The evaluation process is the same with the above

```bash
# aitz_test

python run_eval_agent.py --input_path ./eval_results/aguvis/aitz_test/all.jsonl --output_dir ./eval_results/aguvis/aitz_test/results --data_name aitz_test

# gui_odyssey_test
python run_eval_agent.py --input_path ./eval_results/aguvis/gui_odyssey_test/all.jsonl --output_dir ./eval_results/aguvis/gui_odyssey_test/results --data_name gui_odyssey_test

# chinese_app_test
python run_eval_agent.py --input_path ./eval_results/aguvis/chinese_app_test/all.jsonl --output_dir ./eval_results/aguvis/chinese_app_test/results --data_name chinese_app_test

# android_control_high_test
python run_eval_agent.py --input_path ./eval_results/aguvis/android_control_high_test/all.jsonl --output_dir ./eval_results/aguvis/android_control_high_test/results --data_name android_control_high_test --eval_android_control

# android_control_low_test
python run_eval_agent.py --input_path ./eval_results/aguvis/android_control_low_test/all.jsonl --output_dir ./eval_results/aguvis/android_control_low_test/results --data_name android_control_low_test --eval_android_control
```

---

## OdysseyAgent-Random

### Inference

The OdysseyAgent uses modified model structure, so external code is required to run the code.

Please copy the files of [OdysseyAgent](https://github.com/OpenGVLab/GUI-Odyssey/tree/master/OdysseyAgent) into directory `eval/utils/utils_odyssey`(create the directory first). Then you may proceed with the following command.

```bash
# run only once.
pip install transformers_stream_generator==0.0.4
```

```bash
# aitz_test
python run_predict_odyssey.py --model_path /path/to/model --output_dir ./eval_results/aitz_test --data_name aitz_test

# gui_odyssey_test
python run_predict_odyssey.py --model_path /path/to/model --output_dir ./eval_results/gui_odyssey_test --data_name gui_odyssey_test

# chinese_app_test
python run_predict_odyssey.py --model_path /path/to/model --output_dir ./eval_results/chinese_app_test --data_name chinese_app_test

# android_control_high_test
python run_predict_odyssey.py --model_path /path/to/model --output_dir ./eval_results/android_control_high_test --data_name android_control_high_test

# android_control_low_test
python run_predict_odyssey.py --model_path /path/to/model --output_dir ./eval_results/android_control_low_test --data_name android_control_low_test
```

Additional params include: `--seed`, `--batch_size`, `--num_workers`, `--image_history`, `--his_len`, see the code for more details.


### Eval
The evaluation process is the same with the above.
```bash
# aitz_test
python run_eval_agent.py --input_path ./eval_results/aitz_test/all.jsonl --output_dir ./eval_results/aitz_test/results --data_name aitz_test

# gui_odyssey_test
python run_eval_agent.py --input_path ./eval_results/gui_odyssey_test/all.jsonl --output_dir ./eval_results/gui_odyssey_test/results --data_name gui_odyssey_test

# chinese_app_test
python run_eval_agent.py --input_path ./eval_results/chinese_app_test/all.jsonl --output_dir ./eval_results/chinese_app_test/results --data_name chinese_app_test

# android_control_high_test
python run_eval_agent.py --input_path ./eval_results/android_control_high_test/all.jsonl --output_dir ./eval_results/android_control_high_test/results --data_name android_control_high_test --eval_android_control

# android_control_low_test
python run_eval_agent.py --input_path ./eval_results/android_control_low_test/all.jsonl --output_dir ./eval_results/android_control_low_test/results --data_name android_control_low_test --eval_android_control
```

---

## Grounding Tasks

See [grounding_eval](grounding_eval/README.md) for grounding tasks.

---

## FAQs

1. **Does it support multi-turn history?**

   Yes. Refer to the following data format:
   ```json
    {"image":{"<image_00>":"/home/test/test03/minicpm-a/android_data/processed_data/aitw_message_new/98af1a72bfcadf1209587df1dd82e6e8/images/step_0.png","<image_01>":"/home/test/test03/minicpm-a/android_data/processed_data/aitw_message_new/98af1a72bfcadf1209587df1dd82e6e8/images/step_1.png"},"conversations":[{"role":"system","content":"# Role\n你是一名熟悉安卓系统触屏GUI操作的智能体，将根据用户的问题，分析当前界面的GUI元素和布局，生成相应的操作。\n\n# Task\n针对用户问题，根据输入的当前屏幕截图，输出下一步的操作。\n\n# Rule\n- 以紧凑JSON格式输出\n- 输出操作必须遵循Schema约束\n\n# Schema\n{\"type\":\"object\",\"description\":\"执行操作并决定当前任务状态\",\"additionalProperties\":false,\"optional\":[\"thought\"],\"properties\":{\"thought\":{\"type\":\"string\",\"description\":\"智能体的思维过程\"},\"POINT\":{\"$ref\":\"#/$defs/Location\",\"description\":\"点击屏幕上的指定位置\"},\"to\":{\"description\":\"移动，组合手势参数\",\"oneOf\":[{\"enum\":[\"up\",\"down\",\"left\",\"right\"],\"description\":\"从当前点（POINT）出发，执行滑动手势操作，方向包括向上、向下、向左、向右\"},{\"$ref\":\"#/$defs/Location\",\"description\":\"移动到某个位置\"}]},\"duration\":{\"type\":\"integer\",\"description\":\"动作执行的时间或等待时间，毫秒\",\"minimum\":0,\"default\":200},\"PRESS\":{\"type\":\"string\",\"description\":\"触发特殊按键，HOME为回到主页按钮，BACK为返回按钮，ENTER为回车按钮\",\"enum\":[\"HOME\",\"BACK\",\"ENTER\"]},\"TYPE\":{\"type\":\"string\",\"description\":\"输入文本\"},\"STATUS\":{\"type\":\"string\",\"description\":\"当前任务的状态。特殊情况：satisfied，无需操作；impossible，任务无法完成；interrupt，任务中断；need_feedback，需要用户反馈；\",\"enum\":[\"continue\",\"finish\",\"satisfied\",\"impossible\",\"interrupt\",\"need_feedback\"],\"default\":\"continue\"}},\"$defs\":{\"Location\":{\"type\":\"array\",\"description\":\"坐标为相对于屏幕左上角位原点的相对位置，并且按照宽高比例缩放到0～1000，数组第一个元素为横坐标x，第二个元素为纵坐标y\",\"items\":{\"type\":\"integer\",\"minimum\":0,\"maximum\":1000},\"minItems\":2,\"maxItems\":2}}}"},{"role":"user","content":"<Question>turn on translation in the chrome app</Question>\n当前屏幕截图：<image_00>"},{"role":"assistant","content":"{\"POINT\":[723,536],\"to\":\"up\"}"},{"role":"user","content":"<Question>turn on translation in the chrome app</Question>\n当前屏幕截图：<image_01>"},{"role":"assistant","content":"{\"STATUS\":\"finish\"}"}],"id":0}
   ```

2. **Does it support the open_app action?**


   No. AgentCPM-GUI opens apps by simulating click operations, which reduces backend parsing load but may be unstable. Additionally, we removed the open_app step from the Android Control dataset.
   
3. **How to enable/disable Thought?**  

   You can enable or disable thought by setting the `"required"`/`"optional"` attribute in the schema. See line 35 of `run_predict_minicpm.py`:   
   ```python
   items.insert(insert_index, ("required", ["thought"]))  # enable/disable thought by setting it to "required"/"optional"
   ```

4. **Resolution requirements?**

   It is recommended that the image’s longer side be a maximum of 1120 pixels. Images larger than this should be scaled down proportionally.

5. **What is the coordinate range?**

   AgentCPM-GUI uses relative coordinates ranging from 0-1000. The conversions are as follows:
   ```python
   rel_x, rel_y = [int(abs_x / width * 1000), int(abs_y / height * 1000)]
   abs_x, abs_y = [int(rel_x / 1000 * width), int(rel_y / 1000 * height)]
   ```
   where width and height refer to the original width and height of the image, respectively.
   
6. **Why is `--eval_android_control` needed when evaluating Android Control?**

   This option is required to align with the evaluation function provided by the [Qwen2.5-VL](https://github.com/QwenLM/Qwen2.5-VL/issues/904). Qwen uses different processing methods for different datasets. 

7. **Why is there a gap between your evaluation results and the original paper?**

   Some works have not fully open-sourced the data processing and evaluation scripts used in their experiments, which makes it challenging to reproduce the results. We have made our best effort to debug and achieve optimal results, and we also welcome contributions such as pull requests to help update the results.

8. **How do I run the demo case shown in the video?**
   
   Please refer to this [reply](https://github.com/OpenBMB/AgentCPM-GUI/issues/39#issuecomment-2918489075).

9. **If the model is hosted on a remote server but the Android device can only access the local network, is it still possible to run the demo?**

   Yes. While model inference typically requires a GPU and may not run efficiently on local devices, you can still connect your local Android environment to a remote inference server using SSH port forwarding. For example, you can run:
   ```
   ssh -L localhost:8000:127.0.0.1:8000 root@gpu_server
   ```
   This command forwards the remote server's API to your local machine, allowing you to access the model via `http://localhost:8000/v1/chat/completions` and enable automated interactions from your local Android device.

10. **ValueError: At most 1 image(s) may be provided in one request.**
    
    Please refer to this [issue](https://github.com/OpenBMB/AgentCPM-GUI/issues/39).
