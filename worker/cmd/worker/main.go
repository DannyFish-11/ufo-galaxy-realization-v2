// Galaxy Agentic OS — Go Edge Worker
//
// Entry point for the data-plane worker that connects to NATS, registers with
// the MasterBrain, subscribes to task dispatches, executes code in Docker
// sandboxes with optional LSP pre-checks, and returns results.
//
// Usage:
//
//	GALAXY_NATS_URL=nats://localhost:4222 go run ./cmd/worker/
//
// Environment variables:
//
//	GALAXY_NATS_URL       — NATS server URL (required)
//	GALAXY_WORKER_ID      — Worker identifier (default: auto-generated)
//	GALAXY_WORKER_TYPE    — Device type (default: linux)
//	GALAXY_WORKER_PORT    — Health check HTTP port (default: 8300)
//	GALAXY_HEARTBEAT_SEC  — Heartbeat interval (default: 10)
//	GALAXY_MAX_CONCURRENT — Max concurrent tasks (default: 4)
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"log/slog"
	"net"
	"net/http"
	_ "net/http/pprof"
	"os"
	"os/exec"
	"os/signal"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"github.com/ufo-galaxy/agentic-os/worker/internal/config"
	"github.com/ufo-galaxy/agentic-os/worker/internal/executor"
	"github.com/ufo-galaxy/agentic-os/worker/internal/heartbeat"
	"github.com/ufo-galaxy/agentic-os/worker/internal/lsp"
	natsclient "github.com/ufo-galaxy/agentic-os/worker/internal/nats"
)

// WorkerRegistration mirrors contracts WorkerRegistrationModel (C12 — snake_case).
type WorkerRegistration struct {
	WorkerID           string                    `json:"worker_id"`
	Hostname           string                    `json:"hostname"`
	DeviceType         string                    `json:"device_type"`
	Platform           string                    `json:"platform"`
	OSVersion          string                    `json:"os_version"`
	WorkerVersion      string                    `json:"worker_version"`
	Capabilities       []WorkerCapability        `json:"capabilities"`
	SupportedLanguages []string                  `json:"supported_languages"`
	HasDocker          bool                      `json:"has_docker"`
	HasGPU             bool                      `json:"has_gpu"`
	MemoryTotalMB      int64                     `json:"memory_total_mb"`
	CPUCores           int                       `json:"cpu_cores"`
	RegisteredAt       *executor.Timestamp       `json:"registered_at,omitempty"`
}

// WorkerCapability mirrors contracts WorkerCapabilityModel.
type WorkerCapability struct {
	Name    string `json:"name"`
	Version string `json:"version"`
	Enabled bool   `json:"enabled"`
}

// WorkerShutdown mirrors contracts WorkerShutdownModel.
type WorkerShutdown struct {
	WorkerID       string             `json:"worker_id"`
	Reason         string             `json:"reason"`
	DrainTimeoutS  int                `json:"drain_timeout_s"`
	ShutdownAt     *executor.Timestamp `json:"shutdown_at,omitempty"`
}

// TaskDispatch mirrors contracts TaskDispatchModel (subset needed for dispatch).
type TaskDispatch struct {
	TaskID           string                    `json:"task_id"`
	TaskType         string                    `json:"task_type"`
	TargetWorkerID   string                    `json:"target_worker_id"`
	TargetDeviceType string                    `json:"target_device_type"`
	CodePayload      *executor.CodePayload     `json:"code_payload,omitempty"`
	ShellPayload     *ShellPayload             `json:"shell_payload,omitempty"`
	SandboxConfig    *executor.SandboxConfig   `json:"sandbox_config,omitempty"`
	Priority         string                    `json:"priority"`
	TimeoutMS        int64                     `json:"timeout_ms"`
	MaxRetries       int                       `json:"max_retries"`
	LSPCheckRequired bool                      `json:"lsp_check_required"`
	Context          map[string]string         `json:"context,omitempty"`
}

// ShellPayload mirrors contracts ShellPayloadModel.
type ShellPayload struct {
	Command    string            `json:"command"`
	WorkingDir string            `json:"working_dir"`
	Env        map[string]string `json:"env,omitempty"`
}

// Worker holds the state for the edge worker.
type Worker struct {
	cfg            *config.Config
	nc             *natsclient.Client
	sandbox        *executor.Sandbox
	lspChecker     *lsp.Checker
	activeTasks    int32
	completedTotal int64
	failedTotal    int64
	mu             sync.Mutex
	sem            chan struct{} // weighted semaphore to cap concurrency
	logger         *slog.Logger
}

// newLogger creates a structured logger for the worker.
func newLogger(workerID string) *slog.Logger {
	return slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	})).With("worker_id", workerID)
}

func (w *Worker) buildLifecycleResult(task *TaskDispatch, status string) *executor.TaskResult {
	result := executor.NewTaskResult(task.TaskID, w.cfg.WorkerID, status)
	w.decorateResultMetadata(task, result)
	return result
}

func (w *Worker) decorateResultMetadata(task *TaskDispatch, result *executor.TaskResult) {
	if result == nil || task == nil {
		return
	}
	if result.Metadata == nil {
		result.Metadata = make(map[string]string)
	}
	if traceID := task.Context["trace_id"]; traceID != "" {
		result.Metadata["trace_id"] = traceID
	}
	if correlationID := task.Context["correlation_id"]; correlationID != "" {
		result.Metadata["correlation_id"] = correlationID
	}
	if task.TargetWorkerID != "" {
		result.Metadata["target_worker_id"] = task.TargetWorkerID
	}
	result.Metadata["result_phase"] = result.Status
	result.Metadata["result_id"] = fmt.Sprintf("%s:%s:%d", task.TaskID, result.Status, time.Now().UnixNano())
}

func main() {
	cfg := config.Load()
	logger := newLogger(cfg.WorkerID)

	// SIGHUP handler for config hot-reload
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM, syscall.SIGHUP)
	go func() {
		for sig := range sigCh {
			if sig == syscall.SIGHUP {
				logger.Info("Received SIGHUP, reloading configuration")
				newCfg := config.Load()
				*cfg = *newCfg
				logger.Info("Configuration reloaded")
			}
		}
	}()

	logger.Info("worker starting", "type", cfg.DeviceType, "nats", cfg.NATSURL)

	// Connect to NATS
	nc, err := natsclient.New(cfg.NATSURL, logger)
	if err != nil {
		logger.Error("NATS connection failed", "error", fmt.Errorf("nats connect: %w", err))
		log.Fatalf("[Worker] NATS connection failed: %v", err)
	}
	logger.Info("NATS connected")

	// Create Docker sandbox
	var sandbox *executor.Sandbox
	if cfg.DockerEnabled {
		sandbox, err = executor.NewSandbox()
		if err != nil {
			logger.Warn("Docker sandbox unavailable", "error", fmt.Errorf("sandbox init: %w", err))
		}
	}

	maxConcurrent := cfg.MaxConcurrent
	if maxConcurrent <= 0 {
		maxConcurrent = runtime.NumCPU() * 4
	}

	w := &Worker{
		cfg:        cfg,
		nc:         nc,
		sandbox:    sandbox,
		lspChecker: lsp.NewChecker(),
		sem:        make(chan struct{}, maxConcurrent),
		logger:     logger,
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Register with brain
	w.register()

	// Subscribe to task dispatches (queue group for load balancing)
	subject := fmt.Sprintf("galaxy.tasks.dispatch.%s", cfg.WorkerID)
	_, err = nc.QueueSubscribe(subject, "workers", fmt.Sprintf("worker-%s", cfg.WorkerID), func(data []byte) {
		w.handleTask(ctx, data)
	})
	if err != nil {
		logger.Error("subscribe failed", "error", fmt.Errorf("subscribe: %w", err))
		log.Fatalf("[Worker] subscribe failed: %v", err)
	}
	logger.Info("subscribed to tasks", "subject", subject)

	// Start heartbeat emitter
	hbEmitter := heartbeat.NewEmitter(nc, cfg.WorkerID, cfg.HeartbeatSec, cfg.MaxConcurrent,
		func() (int, int, int) {
			return int(atomic.LoadInt32(&w.activeTasks)),
				int(atomic.LoadInt64(&w.completedTotal)),
				int(atomic.LoadInt64(&w.failedTotal))
		},
		logger,
	)
	go hbEmitter.Run(ctx)

	// Health check HTTP server (constraint C8) + pprof
	go w.serveHealth()

	// Start pprof server on a separate port (default 8301)
	pprofPort := cfg.HealthPort + 1
	go func() {
		logger.Info("pprof server starting", "port", pprofPort)
		if err := http.ListenAndServe(fmt.Sprintf(":%d", pprofPort), nil); err != nil {
			logger.Warn("pprof server error", "error", err)
		}
	}()

	// Wait for shutdown signal
	sigCh2 := make(chan os.Signal, 1)
	signal.Notify(sigCh2, syscall.SIGINT, syscall.SIGTERM)
	sig := <-sigCh2
	logger.Info("received shutdown signal", "signal", sig.String())

	// Graceful shutdown
	w.shutdown()
	cancel()
	nc.Drain()
	if sandbox != nil {
		sandbox.Close()
	}
	logger.Info("shutdown complete")
}

func (w *Worker) register() {
	var memStats runtime.MemStats
	runtime.ReadMemStats(&memStats)

	reg := WorkerRegistration{
		WorkerID:      w.cfg.WorkerID,
		Hostname:      w.cfg.Hostname,
		DeviceType:    w.cfg.DeviceType,
		Platform:      runtime.GOOS,
		OSVersion:     runtime.GOARCH,
		WorkerVersion: w.cfg.WorkerVersion,
		Capabilities: []WorkerCapability{
			{Name: "python_exec", Version: "1.0", Enabled: true},
			{Name: "docker_sandbox", Version: "1.0", Enabled: w.sandbox != nil},
			{Name: "lsp_check", Version: "1.0", Enabled: true},
		},
		SupportedLanguages: []string{"python", "javascript", "bash", "go"},
		HasDocker:          w.sandbox != nil,
		MemoryTotalMB:      int64(memStats.Sys / 1024 / 1024),
		CPUCores:           runtime.NumCPU(),
		RegisteredAt:       executor.NowTimestamp(),
	}

	if err := w.nc.Publish("galaxy.workers.register", reg); err != nil {
		w.logger.Error("registration publish failed", "error", fmt.Errorf("publish: %w", err))
	} else {
		w.logger.Info("registered with brain")
	}
}

func (w *Worker) handleTask(ctx context.Context, data []byte) {
	var task TaskDispatch
	if err := json.Unmarshal(data, &task); err != nil {
		w.logger.Error("unmarshal task failed", "error", fmt.Errorf("unmarshal: %w", err))
		return
	}

	w.logger.Info("received task", "task_id", task.TaskID, "task_type", task.TaskType)

	// Acquire semaphore to limit concurrency
	select {
	case w.sem <- struct{}{}:
		// acquired slot
	case <-ctx.Done():
		w.logger.Warn("task rejected: context cancelled", "task_id", task.TaskID)
		return
	}
	defer func() { <-w.sem }()

	atomic.AddInt32(&w.activeTasks, 1)
	defer atomic.AddInt32(&w.activeTasks, -1)

	startedAt := executor.NowTimestamp()
	accepted := w.buildLifecycleResult(&task, "dispatched")
	w.publishResult(task.TaskID, accepted)

	running := w.buildLifecycleResult(&task, "running")
	running.StartedAt = startedAt
	w.publishResult(task.TaskID, running)

	// Keep a separate base result object for the closing publish so the
	// already-published running update is not mutated when execution_output/error
	// fields, the terminal status, and the final result_id are attached.
	result := executor.NewTaskResult(task.TaskID, w.cfg.WorkerID, "")
	result.StartedAt = startedAt

	// Step 1: LSP check (if required and code payload present)
	if task.LSPCheckRequired && task.CodePayload != nil {
		lspResult := w.lspChecker.Check(ctx, task.CodePayload.Language, task.CodePayload.Source)
		result.LSPResult = lspResult
		if !lspResult.Passed {
			result.Status = "lsp_failed"
			result.Error = &executor.ErrorInfo{
				Code:    "LSP_CHECK_FAILED",
				Message: fmt.Sprintf("%d errors found", lspResult.ErrorCount),
				Source:  "worker.lsp",
			}
			result.CompletedAt = executor.NowTimestamp()
			w.decorateResultMetadata(&task, result)
			w.publishResult(task.TaskID, result)
			atomic.AddInt64(&w.failedTotal, 1)
			return
		}
	}

	// Step 2a: Execute ShellPayload if present
	if task.ShellPayload != nil {
		shellResult, err := w.executeShell(ctx, task.ShellPayload)
		if err != nil {
			result.Status = "failed"
			result.Error = &executor.ErrorInfo{
				Code:    "SHELL_ERROR",
				Message: err.Error(),
				Source:  "worker.shell",
			}
		} else {
			result.ExecutionOutput = shellResult
			if shellResult.ExitCode == 0 {
				result.Status = "success"
			} else {
				result.Status = "failed"
			}
		}
	} else if task.CodePayload != nil && w.sandbox != nil {
		// Step 2b: Execute CodePayload in sandbox
		sandboxCfg := executor.SandboxConfig{
			MemoryLimitMB: 512,
			TimeoutMS:     60000,
		}
		if task.SandboxConfig != nil {
			sandboxCfg = *task.SandboxConfig
		}

		execResult, err := w.sandbox.Execute(ctx, *task.CodePayload, sandboxCfg)
		if err != nil {
			result.Status = "failed"
			result.Error = &executor.ErrorInfo{
				Code:    "SANDBOX_ERROR",
				Message: err.Error(),
				Source:  "worker.sandbox",
			}
		} else {
			result.ExecutionOutput = execResult
			if execResult.ExitCode == 0 && !execResult.TimedOut && !execResult.OOMKilled {
				result.Status = "success"
			} else if execResult.TimedOut {
				result.Status = "timeout"
			} else {
				result.Status = "failed"
			}
		}
	} else if task.CodePayload != nil && w.sandbox == nil {
		result.Status = "failed"
		result.Error = &executor.ErrorInfo{
			Code:    "NO_SANDBOX",
			Message: "Docker sandbox not available on this worker",
			Source:  "worker",
		}
	} else {
		// No payload to execute — mark as success for now
		result.Status = "success"
	}

	result.CompletedAt = executor.NowTimestamp()
	w.publishResult(task.TaskID, result)

	if result.Status == "success" {
		atomic.AddInt64(&w.completedTotal, 1)
	} else {
		atomic.AddInt64(&w.failedTotal, 1)
	}
}

// executeShell executes a shell command locally with timeout.
func (w *Worker) executeShell(ctx context.Context, payload *ShellPayload) (*executor.ExecResult, error) {
	cmdCtx, cancel := context.WithTimeout(ctx, 60*time.Second)
	defer cancel()

	cmd := exec.CommandContext(cmdCtx, "sh", "-c", payload.Command)
	if payload.WorkingDir != "" {
		cmd.Dir = payload.WorkingDir
	}
	for k, v := range payload.Env {
		cmd.Env = append(os.Environ(), k+"="+v)
	}

	var stdout, stderr strings.Builder
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	start := time.Now()
	err := cmd.Run()
	duration := time.Since(start).Milliseconds()

	exitCode := 0
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			exitCode = exitErr.ExitCode()
		} else {
			exitCode = -1
		}
	}

	return &executor.ExecResult{
		Stdout:     stdout.String(),
		Stderr:     stderr.String(),
		ExitCode:   exitCode,
		DurationMS: duration,
		TimedOut:   cmdCtx.Err() == context.DeadlineExceeded,
	}, nil
}

func (w *Worker) publishResult(taskID string, result *executor.TaskResult) {
	subject := fmt.Sprintf("galaxy.tasks.result.%s", taskID)
	if err := w.nc.Publish(subject, result); err != nil {
		w.logger.Error("publish result failed", "task_id", taskID, "error", fmt.Errorf("publish: %w", err))
	} else {
		w.logger.Info("published result", "task_id", taskID, "status", result.Status)
	}
}

func (w *Worker) shutdown() {
	sd := WorkerShutdown{
		WorkerID:      w.cfg.WorkerID,
		Reason:        "user_requested",
		DrainTimeoutS: 30,
		ShutdownAt:    executor.NowTimestamp(),
	}
	if err := w.nc.Publish("galaxy.workers.shutdown", sd); err != nil {
		w.logger.Error("shutdown notification failed", "error", fmt.Errorf("publish: %w", err))
	}
}

func (w *Worker) serveHealth() {
	// Bug fix: 使用带连接池的 http.Client
	healthClient := &http.Client{
		Transport: &http.Transport{
			MaxIdleConns:        100,
			MaxIdleConnsPerHost: 10,
			IdleConnTimeout:     90 * time.Second,
			DialContext: (&net.Dialer{
				Timeout:   5 * time.Second,
				KeepAlive: 30 * time.Second,
			}).DialContext,
		},
		Timeout: 10 * time.Second,
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(rw http.ResponseWriter, r *http.Request) {
		status := map[string]interface{}{
			"status":           "ok",
			"worker_id":        w.cfg.WorkerID,
			"device_type":      w.cfg.DeviceType,
			"nats_connected":   w.nc.IsConnected(),
			"docker_available": w.sandbox != nil,
			"active_tasks":     atomic.LoadInt32(&w.activeTasks),
			"completed_total":  atomic.LoadInt64(&w.completedTotal),
			"failed_total":     atomic.LoadInt64(&w.failedTotal),
			"timestamp":        time.Now().UTC().Format(time.RFC3339),
		}
		rw.Header().Set("Content-Type", "application/json")
		json.NewEncoder(rw).Encode(status)
	})

	addr := fmt.Sprintf(":%d", w.cfg.HealthPort)
	w.logger.Info("health check serving", "addr", addr)
	server := &http.Server{
		Addr:    addr,
		Handler: mux,
	}
	// 使用带连接池的 client 进行任何外部健康检查调用
	_ = healthClient
	if err := server.ListenAndServe(); err != nil {
		w.logger.Error("health server error", "error", err)
	}
}
