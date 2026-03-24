# Galaxy Node-System Audit Report

> Generated: 2026-03-24T03:27:28Z

## Summary Counts

| Metric | Count |
|--------|-------|
| Nominal node directories | 130 |
| Runnable nodes (has main.py + ≥100 lines) | 129 |
| Orchestrated nodes (in node_dependencies.json) | 100 |
| Stub nodes (main.py < 100 lines) | 1 |

## Recommended Actions

| Action | Count | Meaning |
|--------|-------|---------|
| **keep** | 94 | Healthy, orchestrated, no issues |
| **repair** | 31 | Valuable role; fix config/impl before use |
| **archive** | 2 | Non-trivial but not orchestrated; preserve |
| **delete** | 3 | Placeholder/stub/duplicate with no unique value |

## Config Drift

### Nodes in `node_dependencies.json` but NOT on disk
_None — config and disk are in sync for this direction._

### Nodes on disk but NOT in `node_dependencies.json`
- `Node_107_FunctionCalling`
- `Node_108_MetaCognition`
- `Node_109_ProactiveSensing`
- `Node_114_DocumentIntelligence`
- `Node_115_PluginManager`
- `Node_116_ExternalToolWrapper`
- `Node_117_OpenCode`
- `Node_118_NodeFactory`
- `Node_119_BenchmarkEval`
- `Node_120_File`
- `Node_121_Web`
- `Node_122_Shell`
- `Node_124_LinuxDesktopAuto`
- `Node_130_AutonomousCoding`
- `Node_60_ReinforcementLearning`
- `Node_63_FuzzyLogicEngine`
- `Node_70_AutonomousLearning`
- `Node_71_MultiDeviceCoordination`
- `Node_75_DataPipeline`
- `Node_76_AlertManager`
- `Node_77_TaskScheduler`
- `Node_78_DataValidator`
- `Node_86_SpeechProcessor`
- `Node_87_ImageAnalysis`
- `Node_88_WorkflowEngine`
- `Node_89_APIGateway`
- `Node_93_VideoProcessor`
- `Node_94_AudioAnalysis`
- `Node_98_MultimodalFusion`
- `Node_99_EmbeddingService`

### Nodes missing `main.py`
_None — all nominal nodes have a main.py._

### Reserved (placeholder) nodes
- `Node_28_Reserved`
- `Node_29_Reserved`
- `Node_30_Reserved`
- `Node_31_Reserved`
- `Node_32_Reserved`

### Duplicate role nodes
- MediaGen: Node_125_MediaGen, Node_128_MediaGen
- MemorySystem: Node_100_MemorySystem, Node_80_MemorySystem
- Reserved: Node_28_Reserved, Node_29_Reserved, Node_30_Reserved, Node_31_Reserved, Node_32_Reserved

### Numbering gaps
Missing node numbers: [129]

## Node Inventory

| Node | Lines | Group | Port | In Config | Tier | Action | Notes |
|------|-------|-------|------|-----------|------|--------|-------|
| `Node_00_StateMachine` | 390 | core | 8000 | ✓ | orchestrated | **keep** |  |
| `Node_01_OneAPI` | 687 | core | 7995 | ✓ | orchestrated | **keep** |  |
| `Node_02_Tasker` | 316 | core | 8002 | ✓ | orchestrated | **keep** |  |
| `Node_03_SecretVault` | 324 | core | 8003 | ✓ | orchestrated | **keep** |  |
| `Node_04_Router` | 480 | core | 8004 | ✓ | orchestrated | **keep** |  |
| `Node_05_Auth` | 370 | core | 8005 | ✓ | orchestrated | **keep** |  |
| `Node_06_Filesystem` | 354 | core | 8006 | ✓ | orchestrated | **keep** |  |
| `Node_07_Git` | 334 | core | 8007 | ✓ | orchestrated | **keep** |  |
| `Node_08_Fetch` | 199 | core | 8008 | ✓ | orchestrated | **keep** |  |
| `Node_09_Sandbox` | 388 | core | 7996 | ✓ | orchestrated | **keep** |  |
| `Node_100_MemorySystem` | 690 | academic | 8100 | ✓ | orchestrated | **keep** |  |
| `Node_101_CodeEngine` | 612 | academic | 8101 | ✓ | orchestrated | **keep** |  |
| `Node_102_DebugOptimize` | 608 | academic | 8102 | ✓ | orchestrated | **keep** |  |
| `Node_103_KnowledgeGraph` | 650 | academic | 8103 | ✓ | orchestrated | **keep** |  |
| `Node_104_AgentCPM` | 804 | academic | 8104 | ✓ | orchestrated | **keep** |  |
| `Node_105_UnifiedKnowledgeBase` | 546 | academic | 8105 | ✓ | orchestrated | **keep** |  |
| `Node_106_GitHubFlow` | 491 | academic | 8106 | ✓ | orchestrated | **keep** |  |
| `Node_107_FunctionCalling` | 462 | — | — | ✗ | runnable | **repair** | Not in node_dependencies.json — config drift |
| `Node_108_MetaCognition` | 601 | — | — | ✗ | runnable | **repair** | Not in node_dependencies.json — config drift |
| `Node_109_ProactiveSensing` | 532 | — | — | ✗ | runnable | **repair** | Not in node_dependencies.json — config drift |
| `Node_10_Slack` | 232 | development | 8010 | ✓ | orchestrated | **keep** |  |
| `Node_110_SmartOrchestrator` | 664 | core | 7997 | ✓ | orchestrated | **keep** |  |
| `Node_111_ContextManager` | 593 | core | 7998 | ✓ | orchestrated | **keep** |  |
| `Node_112_SelfHealing` | 994 | core | 7999 | ✓ | orchestrated | **keep** |  |
| `Node_113_AndroidVLM` | 278 | enhancement | 8113 | ✓ | orchestrated | **keep** |  |
| `Node_114_DocumentIntelligence` | 321 | — | — | ✗ | runnable | **repair** | Not in node_dependencies.json — config drift |
| `Node_115_PluginManager` | 322 | — | — | ✗ | runnable | **repair** | Not in node_dependencies.json — config drift |
| `Node_116_ExternalToolWrapper` | 498 | — | — | ✗ | runnable | **repair** | Not in node_dependencies.json — config drift |
| `Node_117_OpenCode` | 472 | — | — | ✗ | runnable | **repair** | Not in node_dependencies.json — config drift |
| `Node_118_NodeFactory` | 613 | — | — | ✗ | runnable | **repair** | Not in node_dependencies.json — config drift |
| `Node_119_BenchmarkEval` | 430 | — | — | ✗ | runnable | **repair** | Not in node_dependencies.json — config drift |
| `Node_11_GitHub` | 303 | development | 8011 | ✓ | orchestrated | **keep** |  |
| `Node_120_File` | 748 | — | — | ✗ | runnable | **repair** | Not in node_dependencies.json — config drift |
| `Node_121_Web` | 561 | — | — | ✗ | runnable | **repair** | Not in node_dependencies.json — config drift |
| `Node_122_Shell` | 552 | — | — | ✗ | runnable | **repair** | Not in node_dependencies.json — config drift |
| `Node_123_Calendar` | 223 | development | 8123 | ✓ | orchestrated | **keep** |  |
| `Node_124_LinuxDesktopAuto` | 456 | — | — | ✗ | runnable | **repair** | Not in node_dependencies.json — config drift |
| `Node_125_MediaGen` | 409 | extended | 8125 | ✓ | orchestrated | **keep** |  |
| `Node_126_AgentSwarm` | 981 | extended | 8126 | ✓ | orchestrated | **keep** |  |
| `Node_127_BambuLab` | 172 | extended | 8127 | ✓ | orchestrated | **keep** |  |
| `Node_128_MediaGen` | 316 | extended | 8128 | ✓ | orchestrated | **keep** |  |
| `Node_12_Postgres` | 253 | development | 8012 | ✓ | orchestrated | **keep** |  |
| `Node_130_AutonomousCoding` | 90 | — | — | ✗ | stub | **repair** | main.py only 90 lines — classified as stub; Stub implementation — needs meaningful code before use |
| `Node_13_SQLite` | 230 | development | 8013 | ✓ | orchestrated | **keep** |  |
| `Node_14_FFmpeg` | 253 | development | 8014 | ✓ | orchestrated | **keep** |  |
| `Node_15_OCR` | 293 | development | 8015 | ✓ | orchestrated | **keep** |  |
| `Node_16_Email` | 205 | development | 8016 | ✓ | orchestrated | **keep** |  |
| `Node_17_EdgeTTS` | 149 | development | 8017 | ✓ | orchestrated | **keep** |  |
| `Node_18_DeepL` | 232 | development | 8018 | ✓ | orchestrated | **keep** |  |
| `Node_19_Crypto` | 291 | development | 8019 | ✓ | orchestrated | **keep** |  |
| `Node_20_Qdrant` | 275 | development | 8020 | ✓ | orchestrated | **keep** |  |
| `Node_21_Notion` | 343 | development | 8021 | ✓ | orchestrated | **keep** |  |
| `Node_22_BraveSearch` | 170 | development | 8022 | ✓ | orchestrated | **keep** |  |
| `Node_23_Time` | 225 | development | 9000 | ✓ | orchestrated | **keep** |  |
| `Node_24_Weather` | 260 | development | 8024 | ✓ | orchestrated | **keep** |  |
| `Node_25_GoogleSearch` | 299 | development | 8025 | ✓ | orchestrated | **keep** |  |
| `Node_26_Discord` | 249 | tools | 8023 | ✓ | orchestrated | **repair** | Missing Dockerfile — containerised deployment blocked |
| `Node_27_SmartHome` | 303 | tools | 8027 | ✓ | orchestrated | **keep** |  |
| `Node_28_Reserved` | 252 | development | 8028 | ✓ | orchestrated | **archive** | Node name contains 'Reserved' — placeholder slot |
| `Node_29_Reserved` | 262 | development | 8029 | ✓ | orchestrated | **archive** | Node name contains 'Reserved' — placeholder slot |
| `Node_30_Reserved` | 123 | development | 8030 | ✓ | orchestrated | **delete** | Node name contains 'Reserved' — placeholder slot |
| `Node_31_Reserved` | 123 | extended | 8031 | ✓ | orchestrated | **delete** | Node name contains 'Reserved' — placeholder slot |
| `Node_32_Reserved` | 123 | extended | 8032 | ✓ | orchestrated | **delete** | Node name contains 'Reserved' — placeholder slot |
| `Node_33_ADB` | 499 | extended | 8033 | ✓ | orchestrated | **keep** |  |
| `Node_34_Scrcpy` | 290 | extended | 8034 | ✓ | orchestrated | **keep** |  |
| `Node_35_AppleScript` | 130 | extended | 8035 | ✓ | orchestrated | **keep** |  |
| `Node_36_UIAWindows` | 370 | extended | 8036 | ✓ | orchestrated | **keep** |  |
| `Node_37_LinuxDBus` | 134 | extended | 8037 | ✓ | orchestrated | **keep** |  |
| `Node_38_BLE` | 198 | extended | 8038 | ✓ | orchestrated | **keep** |  |
| `Node_39_SSH` | 186 | extended | 8039 | ✓ | orchestrated | **keep** |  |
| `Node_40_SFTP` | 195 | extended | 8040 | ✓ | orchestrated | **keep** |  |
| `Node_41_MQTT` | 236 | extended | 8041 | ✓ | orchestrated | **keep** |  |
| `Node_42_CANbus` | 164 | extended | 8042 | ✓ | orchestrated | **keep** |  |
| `Node_43_MAVLink` | 141 | extended | 8043 | ✓ | orchestrated | **keep** |  |
| `Node_44_NFC` | 158 | extended | 8044 | ✓ | orchestrated | **keep** |  |
| `Node_45_DesktopAuto` | 198 | extended | 8045 | ✓ | orchestrated | **keep** |  |
| `Node_46_Camera` | 183 | extended | 8046 | ✓ | orchestrated | **keep** |  |
| `Node_47_Audio` | 224 | extended | 8047 | ✓ | orchestrated | **keep** |  |
| `Node_48_Serial` | 190 | extended | 9001 | ✓ | orchestrated | **keep** |  |
| `Node_49_OctoPrint` | 434 | extended | 8049 | ✓ | orchestrated | **keep** |  |
| `Node_50_Transformer` | 294 | extended | 8050 | ✓ | orchestrated | **keep** |  |
| `Node_51_QuantumDispatcher` | 644 | extended | 8051 | ✓ | orchestrated | **keep** |  |
| `Node_52_QiskitSimulator` | 595 | extended | 8052 | ✓ | orchestrated | **keep** |  |
| `Node_53_GraphLogic` | 348 | extended | 8053 | ✓ | orchestrated | **keep** |  |
| `Node_54_SymbolicMath` | 759 | extended | 8054 | ✓ | orchestrated | **keep** |  |
| `Node_55_MultiModal` | 188 | extended | 8055 | ✓ | orchestrated | **keep** |  |
| `Node_56_Planning` | 182 | extended | 9002 | ✓ | orchestrated | **keep** |  |
| `Node_57_QuantumCloud` | 185 | extended | 8057 | ✓ | orchestrated | **keep** |  |
| `Node_58_ModelRouter` | 1057 | extended | 8058 | ✓ | orchestrated | **keep** |  |
| `Node_59_CausalInference` | 149 | extended | 8059 | ✓ | orchestrated | **keep** |  |
| `Node_60_ReinforcementLearning` | 319 | — | — | ✗ | runnable | **repair** | Not in node_dependencies.json — config drift |
| `Node_61_GeometricReasoning` | 166 | extended | 8061 | ✓ | orchestrated | **keep** |  |
| `Node_62_ProbabilisticProgramming` | 135 | extended | 8062 | ✓ | orchestrated | **keep** |  |
| `Node_63_FuzzyLogicEngine` | 399 | — | — | ✗ | runnable | **repair** | Not in node_dependencies.json — config drift |
| `Node_64_Telemetry` | 823 | extended | 8064 | ✓ | orchestrated | **keep** |  |
| `Node_65_LoggerCentral` | 633 | extended | 8065 | ✓ | orchestrated | **keep** |  |
| `Node_66_ConfigManager` | 386 | extended | 8066 | ✓ | orchestrated | **keep** |  |
| `Node_67_HealthMonitor` | 654 | extended | 8067 | ✓ | orchestrated | **keep** |  |
| `Node_68_Security` | 428 | extended | 8068 | ✓ | orchestrated | **keep** |  |
| `Node_69_BackupRestore` | 759 | extended | 8069 | ✓ | orchestrated | **keep** |  |
| `Node_70_AutonomousLearning` | 503 | — | — | ✗ | runnable | **repair** | Not in node_dependencies.json — config drift |
| `Node_71_MultiDeviceCoordination` | 846 | — | — | ✗ | runnable | **repair** | Not in node_dependencies.json — config drift |
| `Node_72_KnowledgeBase` | 414 | extended | 8072 | ✓ | orchestrated | **keep** |  |
| `Node_73_Learning` | 389 | extended | 8073 | ✓ | orchestrated | **keep** |  |
| `Node_74_DigitalTwin` | 403 | extended | 8074 | ✓ | orchestrated | **keep** |  |
| `Node_75_DataPipeline` | 345 | — | — | ✗ | runnable | **repair** | Not in node_dependencies.json — config drift |
| `Node_76_AlertManager` | 335 | — | — | ✗ | runnable | **repair** | Not in node_dependencies.json — config drift |
| `Node_77_TaskScheduler` | 374 | — | — | ✗ | runnable | **repair** | Not in node_dependencies.json — config drift |
| `Node_78_DataValidator` | 303 | — | — | ✗ | runnable | **repair** | Not in node_dependencies.json — config drift |
| `Node_79_LocalLLM` | 798 | extended | 8079 | ✓ | orchestrated | **keep** |  |
| `Node_80_MemorySystem` | 948 | extended | 8080 | ✓ | orchestrated | **keep** |  |
| `Node_81_Orchestrator` | 689 | academic | 8081 | ✓ | orchestrated | **keep** |  |
| `Node_82_NetworkGuard` | 445 | academic | 8082 | ✓ | orchestrated | **keep** |  |
| `Node_83_NewsAggregator` | 468 | academic | 8083 | ✓ | orchestrated | **keep** |  |
| `Node_84_StockTracker` | 482 | academic | 8084 | ✓ | orchestrated | **keep** |  |
| `Node_85_PromptLibrary` | 604 | academic | 8085 | ✓ | orchestrated | **keep** |  |
| `Node_86_SpeechProcessor` | 635 | — | — | ✗ | runnable | **repair** | Not in node_dependencies.json — config drift |
| `Node_87_ImageAnalysis` | 597 | — | — | ✗ | runnable | **repair** | Not in node_dependencies.json — config drift |
| `Node_88_WorkflowEngine` | 597 | — | — | ✗ | runnable | **repair** | Not in node_dependencies.json — config drift |
| `Node_89_APIGateway` | 520 | — | — | ✗ | runnable | **repair** | Not in node_dependencies.json — config drift |
| `Node_90_MultimodalVision` | 590 | academic | 8090 | ✓ | orchestrated | **keep** |  |
| `Node_91_MultimodalAgent` | 419 | academic | 8091 | ✓ | orchestrated | **keep** |  |
| `Node_92_AutoControl` | 307 | academic | 8092 | ✓ | orchestrated | **keep** |  |
| `Node_93_VideoProcessor` | 485 | — | — | ✗ | runnable | **repair** | Not in node_dependencies.json — config drift |
| `Node_94_AudioAnalysis` | 450 | — | — | ✗ | runnable | **repair** | Not in node_dependencies.json — config drift |
| `Node_95_WebRTC_Receiver` | 470 | academic | 8095 | ✓ | orchestrated | **keep** |  |
| `Node_96_SmartTransportRouter` | 412 | academic | 8096 | ✓ | orchestrated | **keep** |  |
| `Node_97_AcademicSearch` | 592 | academic | 8097 | ✓ | orchestrated | **keep** |  |
| `Node_98_MultimodalFusion` | 318 | — | — | ✗ | runnable | **repair** | Not in node_dependencies.json — config drift |
| `Node_99_EmbeddingService` | 317 | — | — | ✗ | runnable | **repair** | Not in node_dependencies.json — config drift |

---
*This report is generated by `scripts/node_audit.py`. Re-run after node changes to refresh.*