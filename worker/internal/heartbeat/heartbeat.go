// Package heartbeat provides periodic heartbeat emission for the Galaxy worker.
//
// Heartbeats are sent every 10s (configurable) to galaxy.workers.heartbeat.
// The MasterBrain uses 3 missed heartbeats (30s) to declare a worker dead.
package heartbeat

import (
	"context"
	"log"
	"runtime"
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
	client       *natsclient.Client
	workerID     string
	interval     time.Duration
	maxConcurrent int
	startTime    time.Time
	getStats     func() (activeTasks, completedTotal, failedTotal int)
}

// NewEmitter creates a heartbeat emitter.
func NewEmitter(
	client *natsclient.Client,
	workerID string,
	intervalSec int,
	maxConcurrent int,
	statsFunc func() (int, int, int),
) *Emitter {
	return &Emitter{
		client:        client,
		workerID:      workerID,
		interval:      time.Duration(intervalSec) * time.Second,
		maxConcurrent: maxConcurrent,
		startTime:     time.Now(),
		getStats:      statsFunc,
	}
}

// Run starts the heartbeat loop. Blocks until context is cancelled.
func (e *Emitter) Run(ctx context.Context) {
	ticker := time.NewTicker(e.interval)
	defer ticker.Stop()

	log.Printf("[Heartbeat] started (interval=%s, worker=%s)", e.interval, e.workerID)

	for {
		select {
		case <-ctx.Done():
			log.Println("[Heartbeat] stopped")
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
		MemoryUsagePercent:  float64(memStats.Alloc) / float64(memStats.Sys) * 100,
		TasksCompletedTotal: int64(completed),
		TasksFailedTotal:    int64(failed),
		UptimeSeconds:       int64(time.Since(e.startTime).Seconds()),
	}

	if active > 0 {
		hb.Status = "busy"
	}

	if err := e.client.Publish("galaxy.workers.heartbeat", hb); err != nil {
		log.Printf("[Heartbeat] publish error: %v", err)
	}
}
