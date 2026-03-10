// Package lsp provides LSP (Language Server Protocol) JSON-RPC types
// for communicating with language servers.
package lsp

// Request is a JSON-RPC 2.0 request.
type Request struct {
	JSONRPC string      `json:"jsonrpc"`
	ID      int         `json:"id"`
	Method  string      `json:"method"`
	Params  interface{} `json:"params,omitempty"`
}

// Response is a JSON-RPC 2.0 response.
type Response struct {
	JSONRPC string      `json:"jsonrpc"`
	ID      int         `json:"id"`
	Result  interface{} `json:"result,omitempty"`
	Error   *RPCError   `json:"error,omitempty"`
}

// RPCError represents a JSON-RPC error.
type RPCError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

// Notification is a JSON-RPC notification (no ID).
type Notification struct {
	JSONRPC string      `json:"jsonrpc"`
	Method  string      `json:"method"`
	Params  interface{} `json:"params,omitempty"`
}

// InitializeParams for the LSP initialize request.
type InitializeParams struct {
	ProcessID  int            `json:"processId"`
	RootURI    string         `json:"rootUri"`
	Capabilities interface{} `json:"capabilities"`
}

// TextDocumentIdentifier identifies a text document.
type TextDocumentIdentifier struct {
	URI string `json:"uri"`
}

// TextDocumentItem for didOpen notification.
type TextDocumentItem struct {
	URI        string `json:"uri"`
	LanguageID string `json:"languageId"`
	Version    int    `json:"version"`
	Text       string `json:"text"`
}

// DidOpenParams for textDocument/didOpen notification.
type DidOpenParams struct {
	TextDocument TextDocumentItem `json:"textDocument"`
}

// DocumentDiagnosticParams for textDocument/diagnostic request.
type DocumentDiagnosticParams struct {
	TextDocument TextDocumentIdentifier `json:"textDocument"`
}

// Diagnostic represents a single LSP diagnostic.
type Diagnostic struct {
	Range    Range  `json:"range"`
	Severity int    `json:"severity"` // 1=Error, 2=Warning, 3=Info, 4=Hint
	Source   string `json:"source"`
	Message  string `json:"message"`
	Code     string `json:"code,omitempty"`
}

// Range is a start-end position pair.
type Range struct {
	Start Position `json:"start"`
	End   Position `json:"end"`
}

// Position is a line+character position (0-based).
type Position struct {
	Line      int `json:"line"`
	Character int `json:"character"`
}

// PublishDiagnosticsParams for textDocument/publishDiagnostics notification.
type PublishDiagnosticsParams struct {
	URI         string       `json:"uri"`
	Diagnostics []Diagnostic `json:"diagnostics"`
}
