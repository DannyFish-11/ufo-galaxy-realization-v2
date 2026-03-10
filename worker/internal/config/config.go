// Package config provides worker configuration from environment variables.
//
// Environment variables (constraint C5 — GALAXY_* prefix):
//
//	GALAXY_NATS_URL       — NATS server URL (default: nats://localhost:4222)
//	GALAXY_WORKER_ID      — Worker identifier (default: auto-generated UUID)
//	GALAXY_WORKER_TYPE    — Device type (default: linux)
//	GALAXY_WORKER_PORT    — Health check HTTP port (default: 8300)
//	GALAXY_HEARTBEAT_SEC  — Heartbeat interval in seconds (default: 10)
//	GALAXY_MAX_CONCURRENT — Maximum concurrent tasks (default: 4)
package config

import (
	"os"
	"strconv"

	"github.com/google/uuid"
)

// Config holds all worker configuration.
type Config struct {
	NATSURL        string
	WorkerID       string
	DeviceType     string
	Hostname       string
	HealthPort     int
	HeartbeatSec   int
	MaxConcurrent  int
	DockerEnabled  bool
	WorkerVersion  string
}

// Load reads configuration from environment variables.
func Load() *Config {
	hostname, _ := os.Hostname()

	c := &Config{
		NATSURL:       envOr("GALAXY_NATS_URL", "nats://localhost:4222"),
		WorkerID:      envOr("GALAXY_WORKER_ID", "worker-"+uuid.New().String()[:8]),
		DeviceType:    envOr("GALAXY_WORKER_TYPE", "linux"),
		Hostname:      hostname,
		HealthPort:    envInt("GALAXY_WORKER_PORT", 8300),
		HeartbeatSec:  envInt("GALAXY_HEARTBEAT_SEC", 10),
		MaxConcurrent: envInt("GALAXY_MAX_CONCURRENT", 4),
		DockerEnabled: envBool("GALAXY_DOCKER_ENABLED", true),
		WorkerVersion: "1.0.0",
	}
	return c
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func envInt(key string, fallback int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return fallback
}

func envBool(key string, fallback bool) bool {
	if v := os.Getenv(key); v != "" {
		b, err := strconv.ParseBool(v)
		if err == nil {
			return b
		}
	}
	return fallback
}
