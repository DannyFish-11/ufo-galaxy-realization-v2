// Package executor provides Docker sandbox execution for the Galaxy edge worker.
//
// It creates an isolated Docker container, mounts the code payload, executes it,
// and captures stdout/stderr/exit_code with resource metrics.
package executor

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"log"
	"strings"
	"time"

	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/client"
	"github.com/docker/docker/pkg/stdcopy"
)

// defaultImages maps CodeLanguage values to Docker images.
var defaultImages = map[string]string{
	"python":     "python:3.12-slim",
	"javascript": "node:20-slim",
	"typescript": "node:20-slim",
	"go":         "golang:1.22-alpine",
	"bash":       "alpine:3.19",
	"rust":       "rust:1.77-slim",
	"c":          "gcc:14",
	"cpp":        "gcc:14",
	"java":       "openjdk:21-slim",
}

// entryCommands maps language to the shell command that runs source from stdin.
var entryCommands = map[string][]string{
	"python":     {"python", "-c"},
	"javascript": {"node", "-e"},
	"typescript": {"node", "-e"},
	"bash":       {"sh", "-c"},
	"go":         {"sh", "-c", "cat > /tmp/main.go && go run /tmp/main.go"},
}

// SandboxConfig mirrors contracts SandboxConfig (constraint C12 — snake_case JSON).
type SandboxConfig struct {
	NetworkEnabled bool     `json:"network_enabled"`
	MemoryLimitMB  int64    `json:"memory_limit_mb"`
	CPULimitMS     int64    `json:"cpu_limit_ms"`
	TimeoutMS      int64    `json:"timeout_ms"`
	DiskLimitMB    int64    `json:"disk_limit_mb"`
	Image          string   `json:"image"`
	MountPaths     []string `json:"mount_paths"`
	GPUEnabled     bool     `json:"gpu_enabled"`
}

// CodePayload mirrors contracts CodePayload.
type CodePayload struct {
	Language     string            `json:"language"`
	Source       string            `json:"source"`
	Entrypoint   string            `json:"entrypoint"`
	Dependencies []string          `json:"dependencies"`
	EnvVars      map[string]string `json:"env_vars"`
	WorkingDir   string            `json:"working_dir"`
}

// ExecResult holds the execution outcome.
type ExecResult struct {
	Stdout     string `json:"stdout"`
	Stderr     string `json:"stderr"`
	ExitCode   int    `json:"exit_code"`
	DurationMS int64  `json:"duration_ms"`
	TimedOut   bool   `json:"timed_out"`
	OOMKilled  bool   `json:"oom_killed"`
}

// Sandbox executes code in a Docker container.
type Sandbox struct {
	cli *client.Client
}

// NewSandbox creates a Sandbox with a Docker client.
func NewSandbox() (*Sandbox, error) {
	cli, err := client.NewClientWithOpts(client.FromEnv, client.WithAPIVersionNegotiation())
	if err != nil {
		return nil, fmt.Errorf("docker client: %w", err)
	}
	return &Sandbox{cli: cli}, nil
}

// Execute runs code in an isolated Docker container.
func (s *Sandbox) Execute(ctx context.Context, code CodePayload, cfg SandboxConfig) (*ExecResult, error) {
	lang := strings.ToLower(code.Language)

	// Select image
	image := cfg.Image
	if image == "" {
		var ok bool
		image, ok = defaultImages[lang]
		if !ok {
			return nil, fmt.Errorf("unsupported language: %s", lang)
		}
	}

	// Build command
	cmd, ok := entryCommands[lang]
	if !ok {
		return nil, fmt.Errorf("no entry command for language: %s", lang)
	}

	// For simple languages, append source as last arg
	if lang != "go" {
		cmd = append(cmd, code.Source)
	}

	// Environment variables
	env := make([]string, 0, len(code.EnvVars))
	for k, v := range code.EnvVars {
		env = append(env, k+"="+v)
	}

	// Memory limit
	memBytes := cfg.MemoryLimitMB * 1024 * 1024
	if memBytes <= 0 {
		memBytes = 512 * 1024 * 1024
	}

	// Timeout
	timeout := time.Duration(cfg.TimeoutMS) * time.Millisecond
	if timeout <= 0 {
		timeout = 60 * time.Second
	}

	// Create container
	containerCfg := &container.Config{
		Image:        image,
		Cmd:          cmd,
		Env:          env,
		WorkingDir:   code.WorkingDir,
		AttachStdout: true,
		AttachStderr: true,
		NetworkDisabled: !cfg.NetworkEnabled,
	}

	hostCfg := &container.HostConfig{
		Resources: container.Resources{
			Memory:   memBytes,
			NanoCPUs: cfg.CPULimitMS * 1_000_000, // Approximate: ms → nano
		},
		AutoRemove: true,
	}

	resp, err := s.cli.ContainerCreate(ctx, containerCfg, hostCfg, nil, nil, "")
	if err != nil {
		return nil, fmt.Errorf("container create: %w", err)
	}
	containerID := resp.ID

	// Attach to capture output
	attachResp, err := s.cli.ContainerAttach(ctx, containerID, container.AttachOptions{
		Stream: true,
		Stdout: true,
		Stderr: true,
	})
	if err != nil {
		return nil, fmt.Errorf("container attach: %w", err)
	}
	defer attachResp.Close()

	// Start container
	start := time.Now()
	if err := s.cli.ContainerStart(ctx, containerID, container.StartOptions{}); err != nil {
		return nil, fmt.Errorf("container start: %w", err)
	}

	// Wait with timeout
	waitCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	statusCh, errCh := s.cli.ContainerWait(waitCtx, containerID, container.WaitConditionNotRunning)

	var result ExecResult

	// Read output
	var stdoutBuf, stderrBuf bytes.Buffer
	go func() {
		stdcopy.StdCopy(&stdoutBuf, &stderrBuf, attachResp.Reader)
	}()

	select {
	case err := <-errCh:
		if err != nil {
			// Likely timeout
			result.TimedOut = true
			s.cli.ContainerKill(ctx, containerID, "KILL")
		}
	case status := <-statusCh:
		result.ExitCode = int(status.StatusCode)
		if status.Error != nil {
			result.Stderr = status.Error.Message
		}
	}

	result.DurationMS = time.Since(start).Milliseconds()

	// Truncate output at 1MB
	result.Stdout = truncate(stdoutBuf.String(), 1_048_576)
	result.Stderr = truncate(stderrBuf.String(), 1_048_576)

	// Check OOM
	inspectResp, err := s.cli.ContainerInspect(ctx, containerID)
	if err == nil && inspectResp.State != nil {
		result.OOMKilled = inspectResp.State.OOMKilled
	}

	log.Printf("[Sandbox] execution complete: lang=%s exit=%d duration=%dms",
		lang, result.ExitCode, result.DurationMS)

	return &result, nil
}

// Close cleans up the Docker client.
func (s *Sandbox) Close() error {
	return s.cli.Close()
}

func truncate(s string, max int) string {
	if len(s) > max {
		return s[:max] + "\n... [truncated]"
	}
	return s
}

// Ensure io is used (for stdcopy reader)
var _ = io.Discard
