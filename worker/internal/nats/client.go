// Package natsclient wraps the NATS connection for the Galaxy edge worker.
//
// Wire format (constraint C12):
//   - JSON encoding, snake_case field names matching Python Pydantic models.
//   - Binary Protobuf is a future optimization.
package natsclient

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	"github.com/nats-io/nats.go"
)

// Client manages the NATS connection and JetStream context.
type Client struct {
	nc     *nats.Conn
	js     nats.JetStreamContext
	url    string
	logger *slog.Logger
}

// New creates a NATS client and connects to the server.
func New(url string, logger *slog.Logger) (*Client, error) {
	opts := []nats.Option{
		nats.MaxReconnects(-1),
		nats.ReconnectWait(2 * time.Second),
		nats.DisconnectErrHandler(func(_ *nats.Conn, err error) {
			logger.Warn("NATS disconnected", "error", fmt.Errorf("disconnect: %w", err))
		}),
		nats.ReconnectHandler(func(_ *nats.Conn) {
			logger.Info("NATS reconnected")
		}),
	}

	nc, err := nats.Connect(url, opts...)
	if err != nil {
		return nil, fmt.Errorf("nats connect: %w", err)
	}

	js, err := nc.JetStream()
	if err != nil {
		nc.Close()
		return nil, fmt.Errorf("jetstream init: %w", err)
	}

	return &Client{nc: nc, js: js, url: url, logger: logger}, nil
}

// Publish serializes data as JSON and publishes to a JetStream subject.
func (c *Client) Publish(subject string, data interface{}) error {
	payload, err := json.Marshal(data)
	if err != nil {
		return fmt.Errorf("marshal: %w", err)
	}
	_, err = c.js.Publish(subject, payload)
	if err != nil {
		return fmt.Errorf("jetstream publish %s: %w", subject, err)
	}
	return nil
}

// safeHandler wraps the user handler with panic recovery.
func safeHandler(handler func([]byte)) func(*nats.Msg) {
	return func(msg *nats.Msg) {
		// Bug fix: NATS handler panic 崩溃保护
		defer func() {
			if r := recover(); r != nil {
				log.Printf("[NATS] handler panic recovered: %v", r)
			}
		}()
		handler(msg.Data)
		msg.Ack()
	}
}

// Subscribe creates a durable JetStream subscription with a message handler.
func (c *Client) Subscribe(subject, durable string, handler func([]byte)) (*nats.Subscription, error) {
	sub, err := c.js.Subscribe(subject, safeHandler(handler), nats.Durable(durable))
	if err != nil {
		return nil, fmt.Errorf("subscribe %s: %w", subject, err)
	}
	return sub, nil
}

// QueueSubscribe creates a durable queue subscription for load balancing.
func (c *Client) QueueSubscribe(subject, queue, durable string, handler func([]byte)) (*nats.Subscription, error) {
	sub, err := c.js.QueueSubscribe(subject, queue, safeHandler(handler), nats.Durable(durable))
	if err != nil {
		return nil, fmt.Errorf("queue subscribe %s: %w", subject, err)
	}
	return sub, nil
}

// Drain gracefully drains and closes the connection.
func (c *Client) Drain() error {
	return c.nc.Drain()
}

// IsConnected returns true if the connection is active.
func (c *Client) IsConnected() bool {
	return c.nc != nil && c.nc.IsConnected()
}
