// Package executor — result assembly for TaskResult messages.
//
// JSON field names match Pydantic model fields exactly (constraint C12).
package executor

import (
	"time"
)

// TaskResult mirrors contracts TaskResultModel (snake_case JSON).
type TaskResult struct {
	TaskID          string            `json:"task_id"`
	WorkerID        string            `json:"worker_id"`
	Status          string            `json:"status"`
	LSPResult       *LSPCheckResult   `json:"lsp_result,omitempty"`
	ExecutionOutput *ExecResult       `json:"execution_output,omitempty"`
	Artifacts       []Artifact        `json:"artifacts,omitempty"`
	ResourceUsage   *ResourceUsage    `json:"resource_usage,omitempty"`
	Error           *ErrorInfo        `json:"error,omitempty"`
	AttemptNumber   int               `json:"attempt_number"`
	StartedAt       *Timestamp        `json:"started_at,omitempty"`
	CompletedAt     *Timestamp        `json:"completed_at,omitempty"`
	QueueWaitMS     int64             `json:"queue_wait_ms"`
	Metadata        map[string]string `json:"metadata,omitempty"`
}

// LSPCheckResult mirrors contracts LSPCheckResultModel.
type LSPCheckResult struct {
	Passed          bool              `json:"passed"`
	Diagnostics     []LSPDiagnostic   `json:"diagnostics,omitempty"`
	ErrorCount      int               `json:"error_count"`
	WarningCount    int               `json:"warning_count"`
	CheckDurationMS int64             `json:"check_duration_ms"`
}

// LSPDiagnostic mirrors contracts LSPDiagnosticModel.
type LSPDiagnostic struct {
	FilePath string `json:"file_path"`
	Line     int    `json:"line"`
	Column   int    `json:"column"`
	Severity string `json:"severity"`
	Message  string `json:"message"`
	Source   string `json:"source"`
	Code     string `json:"code"`
}

// Artifact mirrors contracts ArtifactModel.
type Artifact struct {
	Name      string `json:"name"`
	Path      string `json:"path"`
	MimeType  string `json:"mime_type"`
	SizeBytes int64  `json:"size_bytes"`
	Checksum  string `json:"checksum"`
}

// ResourceUsage mirrors contracts ResourceUsageModel.
type ResourceUsage struct {
	MemoryPeakBytes int64 `json:"memory_peak_bytes"`
	CPUTimeMS       int64 `json:"cpu_time_ms"`
	WallTimeMS      int64 `json:"wall_time_ms"`
	DiskReadBytes   int64 `json:"disk_read_bytes"`
	DiskWriteBytes  int64 `json:"disk_write_bytes"`
	NetworkRxBytes  int64 `json:"network_rx_bytes"`
	NetworkTxBytes  int64 `json:"network_tx_bytes"`
}

// ErrorInfo mirrors contracts ErrorInfoModel.
type ErrorInfo struct {
	Code    string `json:"code"`
	Message string `json:"message"`
	Details string `json:"details"`
	Source  string `json:"source"`
}

// Timestamp mirrors contracts TimestampModel.
type Timestamp struct {
	Seconds int64 `json:"seconds"`
	Nanos   int32 `json:"nanos"`
}

// NowTimestamp returns a Timestamp for the current time.
func NowTimestamp() *Timestamp {
	now := time.Now()
	return &Timestamp{
		Seconds: now.Unix(),
		Nanos:   int32(now.Nanosecond()),
	}
}

// NewTaskResult creates a TaskResult with default values.
func NewTaskResult(taskID, workerID, status string) *TaskResult {
	return &TaskResult{
		TaskID:        taskID,
		WorkerID:      workerID,
		Status:        status,
		AttemptNumber: 1,
		CompletedAt:   NowTimestamp(),
		Metadata:      make(map[string]string),
	}
}
