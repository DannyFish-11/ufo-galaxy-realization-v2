# Node_62_ProbabilisticProgramming

概率编程服务节点，提供贝叶斯推断、采样、马尔可夫链蒙特卡洛等概率计算能力。

## 端口
8062

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /bayes` - 贝叶斯推断
- `POST /sample` - 概率采样
- `POST /mcmc` - MCMC 采样
- `POST /likelihood` - 似然度计算
