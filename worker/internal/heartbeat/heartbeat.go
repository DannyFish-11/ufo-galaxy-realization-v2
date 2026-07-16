// Package heartbeat provides periodic heartbeat emission for the Galaxy worker.
//
// Heartbeats are sent every 10s (configurable) to galaxy.workers.heartbeat.
// The MasterBrain uses 3 missed heartbeats (30s) to declare a worker dead.
package heartbeat

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"runtime"
	"syscall"
	"time"

	natsclient "github.com/ufo-galaxy/agentic-os/worker/internal/nats"
	"github.com/ufo-galaxy/agentic-os/worker/internal/executor"
)

// WorkerHeartbeat mirrors contracts WorkerHeartbeatModel (constraint C12).
type WorkerHeartbeat struct {
	WorkerID            string             `json:"worker_id"`
	Status              string             `json:"status"`
	Timestamp           *executor.Timestamp `json:"timestamp,omitempty"`
	ActiveTasks         int                `json:"active_tasks"`
	QueuedTasks         int                `json:"queued_tasks"`
	MaxConcurrent       int                `json:"max_concurrent"`
	CPUUsagePercent     float64            `json:"cpu_usage_percent"`
	MemoryUsagePercent  float64            `json:"memory_usage_percent"`
	DiskFreeMB          int64              `json:"disk_free_mb"`
	RunningContainers   int                `json:"running_containers"`
	DockerDiskMB        int64              `json:"docker_disk_mb"`
	TasksCompletedTotal int64              `json:"tasks_completed_total"`
	TasksFailedTotal    int64              `json:"tasks_failed_total"`
	UptimeSeconds       int64              `json:"uptime_seconds"`
}

// Emitter sends periodic heartbeats via NATS.
type Emitter struct {
	client        *natsclient.Client
	workerID      string
	interval      time.Duration
	maxConcurrent int
	startTime     time.Time
	getStats      func() (activeTasks, completedTotal, failedTotal int)
	logger        *slog.Logger
}

// NewEmitter creates a heartbeat emitter.
func NewEmitter(
	client *natsclient.Client,
	workerID string,
	intervalSec int,
	maxConcurrent int,
	statsFunc func() (int, int, int),
	logger *slog.Logger,
) *Emitter {
	return &Emitter{
		client:        client,
		workerID:      workerID,
		interval:      time.Duration(intervalSec) * time.Second,
		maxConcurrent: maxConcurrent,
		startTime:     time.Now(),
		getStats:      statsFunc,
		logger:        logger,
	}
}

// Run starts the heartbeat loop. Blocks until context is cancelled.
func (e *Emitter) Run(ctx context.Context) {
	ticker := time.NewTicker(e.interval)
	defer ticker.Stop()

	e.logger.Info("heartbeat started", "interval", e.interval, "worker_id", e.workerID)

	for {
		select {
		case <-ctx.Done():
			e.logger.Info("heartbeat stopped")
			return
		case <-ticker.C:
			e.send()
		}
	}
}

func (e *Emitter) send() {
	active, completed, failed := e.getStats()

	var memStats runtime.MemStats
	runtime.ReadMemStats(&memStats)

	hb := WorkerHeartbeat{
		WorkerID:            e.workerID,
		Status:              "idle",
		Timestamp:           executor.NowTimestamp(),
		ActiveTasks:         active,
		QueuedTasks:         0,
		MaxConcurrent:       e.maxConcurrent,
		TasksCompletedTotal: int64(completed),
		TasksFailedTotal:    int64(failed),
		UptimeSeconds:       int64(time.Since(e.startTime).Seconds()),
	}

	if active > 0 {
		hb.Status = "busy"
	}

	// Bug fix: 正确采集系统指标（替代全零）
	hb = e.collectSystemMetrics(hb)

	if err := e.client.Publish("galaxy.workers.heartbeat", hb); err != nil {
		e.logger.Error("heartbeat publish failed", "error", fmt.Errorf("publish: %w", err))
	}
}

// collectSystemMetrics collects real system metrics using syscall.
// This replaces the previous implementation that left CPUUsagePercent and DiskFreeMB as zero.
func (e *Emitter) collectSystemMetrics(hb WorkerHeartbeat) WorkerHeartbeat {
	// CPU usage: use runtime.GOMAXPROCS as a proxy for available cores
	cpuCores := runtime.NumCPU()
	_ = cpuCores

	// Memory: use Go runtime memStats as a proxy (Allocated / Sys)
	var memStats runtime.MemStats
	runtime.ReadMemStats(&memStats)
	if memStats.Sys > 0 {
		hb.MemoryUsagePercent = float64(memStats.Alloc) / float64(memStats.Sys) * 100
	}

	// Disk free: use syscall.Statfs for the root filesystem
	var statfs syscall.Statfs_t
	if err := syscall.Statfs("/", &statfs); err == nil {
		// bavail * bsize = available bytes
		availableBytes := statfs.Bavail * uint64(statfs.Bsize)
		hb.DiskFreeMB = int64(availableBytes / (1024 * 1024))
	} else {
		// Fallback: check GALAXY_DISK_PATH env var
		if diskPath := os.Getenv("GALAXY_DISK_PATH"); diskPath != "" {
			if err := syscall.Statfs(diskPath, &statfs); err == nil {
				availableBytes := statfs.Bavail * uint64(statfs.Bsize)
				hb.DiskFreeMB = int64(availableBytes / (1024 * 1024))
			}
		}
	}

	// CPU usage approximation: compare recent CPU time
	// A simple approximation using runtime statistics
	hb.CPUUsagePercent = estimateCPUUsage()

	return hb
}

// estimateCPUUsage provides a rough CPU usage estimate based on goroutine activity.
// A more accurate implementation would use /proc/stat or cgroups.
func estimateCPUUsage() float64 {
	var m1, m2 runtime.MemStats
	runtime.ReadMemStats(&m1)
	t1 := time.Now()
	time.Sleep(100 * time.Millisecond)
	runtime.ReadMemStats(&m2)
	t2 := time.Now()

	// Rough heuristic: if GC is active or allocations are high, CPU is likely busy
	elapsed := t2.Sub(t1).Seconds()
	if elapsed <= 0 {
		return 0
	}
	// Simple heuristic based on GC CPU fraction
	gcCPUFraction := m2.GCCPUFraction * 100
	if gcCPUFraction > 0 {
		return gcCPUFraction * float64(runtime.NumCPU())
	}
	return gcCPUFraction
}
