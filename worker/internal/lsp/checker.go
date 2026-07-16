// Package lsp provides an LSP diagnostic checker for code pre-validation.
//
// It spawns a language server process, sends textDocument/didOpen, collects
// diagnostics, and returns an LSPCheckResult.
//
// Supported language servers:
//   - Python: pylsp (pip install python-lsp-server)
//   - Go: gopls (go install golang.org/x/tools/gopls@latest)
//   - JavaScript/TypeScript: typescript-language-server
package lsp

import (
	"fmt"
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/ufo-galaxy/agentic-os/worker/internal/executor"
)

// serverCommands maps language to the LSP server command.
var serverCommands = map[string][]string{
	"python":     {"pylsp"},
	"go":         {"gopls", "serve"},
	"javascript": {"typescript-language-server", "--stdio"},
	"typescript": {"typescript-language-server", "--stdio"},
}

// languageIDs maps language name to LSP language identifier.
var languageIDs = map[string]string{
	"python":     "python",
	"go":         "go",
	"javascript": "javascript",
	"typescript": "typescript",
}

// lspProcess holds a reusable LSP server process.
type lspProcess struct {
	cmd    *exec.Cmd
	stdin  io.WriteCloser
	stdout io.ReadCloser
	mu     sync.Mutex
}

// Checker runs LSP diagnostics on source code with process pooling.
type Checker struct {
	processes map[string]*lspProcess // language -> reusable process
	mu        sync.RWMutex
}

// NewChecker creates a new LSP checker.
func NewChecker() *Checker {
	return &Checker{
		processes: make(map[string]*lspProcess),
	}
}

// getOrCreateProcess gets a cached LSP process or creates a new one.
func (c *Checker) getOrCreateProcess(lang string) (*lspProcess, bool) {
	c.mu.RLock()
	proc, exists := c.processes[lang]
	c.mu.RUnlock()
	if exists && proc.cmd.Process != nil {
		return proc, true
	}
	return nil, false
}

// cacheProcess caches an LSP process for reuse.
func (c *Checker) cacheProcess(lang string, proc *lspProcess) {
	c.mu.Lock()
	// Kill old process if exists
	if old, exists := c.processes[lang]; exists && old.cmd.Process != nil {
		old.cmd.Process.Kill()
	}
	c.processes[lang] = proc
	c.mu.Unlock()
}

// Cleanup kills all cached LSP processes.
func (c *Checker) Cleanup() {
	c.mu.Lock()
	defer c.mu.Unlock()
	for _, proc := range c.processes {
		if proc.cmd.Process != nil {
			proc.cmd.Process.Kill()
		}
	}
	c.processes = make(map[string]*lspProcess)
}

// Check runs LSP diagnostics on the given source code.
//
// Returns an LSPCheckResult (from executor package) with pass/fail and
// diagnostic details.  If the language server is not available, it returns
// a passing result (graceful degradation).
// Bug fix: 使用进程池复用 LSP 进程，避免频繁创建销毁。
func (c *Checker) Check(ctx context.Context, language, source string) *executor.LSPCheckResult {
	result := &executor.LSPCheckResult{Passed: true}
	start := time.Now()

	cmdCfg, ok := serverCommands[strings.ToLower(language)]
	if !ok {
		log.Printf("[LSP] no server for language %s, skipping check", language)
		return result
	}

	langID, _ := languageIDs[strings.ToLower(language)]
	if langID == "" {
		langID = strings.ToLower(language)
	}

	// Check if server binary exists
	if _, err := exec.LookPath(cmdCfg[0]); err != nil {
		log.Printf("[LSP] %s not found, skipping check", cmdCfg[0])
		return result
	}

	// 尝试复用缓存的进程
	proc, reused := c.getOrCreateProcess(language)
	if !reused {
		// 创建新进程并缓存
		serverCtx, cancel := context.WithTimeout(ctx, 15*time.Second)
		defer cancel()

		newProc := exec.CommandContext(serverCtx, cmdCfg[0], cmdCfg[1:]...)
		stdin, err := newProc.StdinPipe()
		if err != nil {
			log.Printf("[LSP] stdin pipe error: %v", err)
			return result
		}
		stdout, err := newProc.StdoutPipe()
		if err != nil {
			log.Printf("[LSP] stdout pipe error: %v", err)
			return result
		}

		if err := newProc.Start(); err != nil {
			log.Printf("[LSP] failed to start %s: %v", cmdCfg[0], err)
			return result
		}

		proc = &lspProcess{
			cmd:    newProc,
			stdin:  stdin,
			stdout: stdout,
		}
		c.cacheProcess(language, proc)

		// 首次使用：发送 initialize 请求
		reader := bufio.NewReader(stdout)
		initParams := InitializeParams{
			ProcessID:    newProc.Process.Pid,
			RootURI:      "file:///tmp/galaxy-lsp",
			Capabilities: map[string]interface{}{},
		}
		if err := sendRequest(stdin, 1, "initialize", initParams); err != nil {
			log.Printf("[LSP] initialize send error: %v", err)
			return result
		}
		if _, err := readResponse(reader); err != nil {
			log.Printf("[LSP] initialize response error: %v", err)
			return result
		}
		sendNotification(stdin, "initialized", map[string]interface{}{})
	}

	// 使用进程进行检查（复用或新创建）
	proc.mu.Lock()
	defer proc.mu.Unlock()

	reader := bufio.NewReader(proc.stdout)

	// Send didOpen
	docURI := "file:///tmp/galaxy-lsp/check.py"
	if language == "go" {
		docURI = "file:///tmp/galaxy-lsp/check.go"
	} else if language == "javascript" || language == "typescript" {
		docURI = "file:///tmp/galaxy-lsp/check.js"
	}

	openParams := DidOpenParams{
		TextDocument: TextDocumentItem{
			URI:        docURI,
			LanguageID: langID,
			Version:    1,
			Text:       source,
		},
	}
	sendNotification(proc.stdin, "textDocument/didOpen", openParams)

	// Wait for diagnostics (published as notifications)
	diagnostics := collectDiagnostics(reader, 5*time.Second)

	result.CheckDurationMS = time.Since(start).Milliseconds()

	for _, d := range diagnostics {
		diag := executor.LSPDiagnostic{
			FilePath: docURI,
			Line:     d.Range.Start.Line + 1, // Convert 0-based to 1-based
			Column:   d.Range.Start.Character + 1,
			Message:  d.Message,
			Source:   d.Source,
			Code:     d.Code,
		}
		switch d.Severity {
		case 1:
			diag.Severity = "error"
			result.ErrorCount++
		case 2:
			diag.Severity = "warning"
			result.WarningCount++
		case 3:
			diag.Severity = "info"
		case 4:
			diag.Severity = "hint"
		default:
			diag.Severity = "info"
		}
		result.Diagnostics = append(result.Diagnostics, diag)
	}

	result.Passed = result.ErrorCount == 0
	log.Printf("[LSP] check complete: passed=%v errors=%d warnings=%d duration=%dms reused=%v",
		result.Passed, result.ErrorCount, result.WarningCount, result.CheckDurationMS, reused)

	return result
}

// sendRequest sends a JSON-RPC request over LSP content-length framing.
func sendRequest(w io.Writer, id int, method string, params interface{}) error {
	req := Request{JSONRPC: "2.0", ID: id, Method: method, Params: params}
	body, err := json.Marshal(req)
	if err != nil {
		return err
	}
	header := fmt.Sprintf("Content-Length: %d\r\n\r\n", len(body))
	_, err = w.Write(append([]byte(header), body...))
	return err
}

// sendNotification sends a JSON-RPC notification.
func sendNotification(w io.Writer, method string, params interface{}) error {
	notif := Notification{JSONRPC: "2.0", Method: method, Params: params}
	body, err := json.Marshal(notif)
	if err != nil {
		return err
	}
	header := fmt.Sprintf("Content-Length: %d\r\n\r\n", len(body))
	_, err = w.Write(append([]byte(header), body...))
	return err
}

// readResponse reads a single LSP response (Content-Length framed).
func readResponse(r *bufio.Reader) ([]byte, error) {
	// Read headers
	contentLen := 0
	for {
		line, err := r.ReadString('\n')
		if err != nil {
			return nil, err
		}
		line = strings.TrimSpace(line)
		if line == "" {
			break
		}
		if strings.HasPrefix(line, "Content-Length:") {
			n, _ := strconv.Atoi(strings.TrimSpace(strings.TrimPrefix(line, "Content-Length:")))
			contentLen = n
		}
	}

	if contentLen == 0 {
		return nil, fmt.Errorf("no Content-Length header")
	}

	body := make([]byte, contentLen)
	_, err := io.ReadFull(r, body)
	return body, err
}

// collectDiagnostics reads LSP messages for the given duration, collecting
// publishDiagnostics notifications.
func collectDiagnostics(r *bufio.Reader, timeout time.Duration) []Diagnostic {
	var all []Diagnostic
	deadline := time.After(timeout)

	for {
		select {
		case <-deadline:
			return all
		default:
			body, err := readResponse(r)
			if err != nil {
				return all
			}

			var msg struct {
				Method string          `json:"method"`
				Params json.RawMessage `json:"params"`
			}
			if err := json.Unmarshal(body, &msg); err != nil {
				continue
			}

			if msg.Method == "textDocument/publishDiagnostics" {
				var params PublishDiagnosticsParams
				if err := json.Unmarshal(msg.Params, &params); err == nil {
					all = append(all, params.Diagnostics...)
				}
				return all // Got diagnostics, return immediately
			}
		}
	}
}
