/**
 * dashboard/frontend/ts/mesh_console.ts
 * ========================================
 * Block-4: Manifest Mesh Console
 *
 * Provides:
 *   - MeshTopology: reactive data model for body-mesh topology
 *   - MeshConsoleAPI: API client for /api/v1/mesh/* and related endpoints
 *   - renderMeshConsole(): mount a minimal mesh visualisation into a DOM node
 */

// ============================================================================
// Type definitions
// ============================================================================

export type DeviceRole = "perception" | "action" | "presence";

export interface BodyEntry {
  device_id: string;
  roles: DeviceRole[];
  session_id: string | null;
  body_score: number;
  registered_at: number;
  metadata: Record<string, unknown>;
}

export interface BodyAssignment {
  primary_body: BodyEntry | null;
  secondary_bodies: BodyEntry[];
  session_id: string | null;
  computed_at: number;
}

export interface MeshTopologySnapshot {
  total: number;
  entries: BodyEntry[];
}

export interface HealthScore {
  device_id: string;
  total_score: number;
  latency_score: number;
  error_rate_score: number;
  jitter_score: number;
  heartbeat_score: number;
  sample_count: number;
  computed_at: number;
}

export interface AllHealthScores {
  total_devices: number;
  scores: Record<string, HealthScore>;
}

export interface ProjectionEvent {
  projection_id: string;
  device_id: string;
  session_id: string | null;
  trace_id: string | null;
  cognitive_state: Record<string, unknown>;
  intensity: number;
  roles: string[];
  projected_at: number;
}

export interface HITLRequest {
  request_id: string;
  action: string;
  context: Record<string, unknown>;
  session_id: string | null;
  trace_id: string | null;
  is_high_risk: boolean;
  created_at: number;
  expires_at: number;
  decision: HITLDecision | null;
  is_pending: boolean;
}

export interface HITLDecision {
  request_id: string;
  outcome: "approved" | "rejected" | "timeout";
  approved: boolean;
  reason: string;
  decided_by: string;
  decided_at: number;
  trace_id: string | null;
}

// ============================================================================
// MeshConsoleAPI — thin fetch wrapper
// ============================================================================

const BASE = "";  // same origin

export class MeshConsoleAPI {
  /** Fetch full mesh topology snapshot. */
  static async getTopology(): Promise<MeshTopologySnapshot> {
    const r = await fetch(`${BASE}/api/v1/mesh/topology`);
    return r.json();
  }

  /** Compute primary/secondary body assignment for an optional session. */
  static async getAssignment(sessionId?: string): Promise<BodyAssignment> {
    const qs = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
    const r = await fetch(`${BASE}/api/v1/mesh/assignment${qs}`);
    return r.json();
  }

  /** Trigger device role allocation. */
  static async allocate(sessionId?: string): Promise<{ success: boolean; allocated: unknown[] }> {
    const qs = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
    const r = await fetch(`${BASE}/api/v1/mesh/allocate${qs}`, { method: "POST" });
    return r.json();
  }

  /** Fetch health scores for all devices. */
  static async getAllHealth(): Promise<AllHealthScores> {
    const r = await fetch(`${BASE}/api/v1/devices/health`);
    return r.json();
  }

  /** Fetch health score for one device. */
  static async getDeviceHealth(deviceId: string): Promise<HealthScore> {
    const r = await fetch(`${BASE}/api/v1/devices/${encodeURIComponent(deviceId)}/health`);
    return r.json();
  }

  /** Fetch pending HITL requests. */
  static async getPendingHITL(): Promise<{ pending: HITLRequest[]; count: number }> {
    const r = await fetch(`${BASE}/api/v1/hitl/requests`);
    return r.json();
  }

  /** Submit a HITL decision. */
  static async submitHITLDecision(
    requestId: string,
    approve: boolean,
    reason = "",
    decidedBy = "dashboard_user"
  ): Promise<{ success: boolean; decision?: HITLDecision }> {
    const r = await fetch(`${BASE}/api/v1/hitl/decide`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        request_id: requestId,
        approve,
        reason,
        decided_by: decidedBy,
      }),
    });
    return r.json();
  }

  /** Get recent presence projection events. */
  static async getPresenceEvents(n = 20): Promise<{ events: ProjectionEvent[] }> {
    const r = await fetch(`${BASE}/api/v1/presence/events?n=${n}`);
    return r.json();
  }

  /** Trigger a manual presence projection for a session. */
  static async triggerPresenceProjection(
    sessionId?: string
  ): Promise<{ success: boolean; projected_to: number; events: ProjectionEvent[] }> {
    const qs = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
    const r = await fetch(`${BASE}/api/v1/presence/project${qs}`, { method: "POST" });
    return r.json();
  }
}

// ============================================================================
// MeshTopology — reactive state model (vanilla TS, no framework required)
// ============================================================================

export class MeshTopology {
  topology: MeshTopologySnapshot = { total: 0, entries: [] };
  assignment: BodyAssignment | null = null;
  health: AllHealthScores = { total_devices: 0, scores: {} };
  pendingHITL: HITLRequest[] = [];
  presenceEvents: ProjectionEvent[] = [];

  private _listeners: Array<() => void> = [];

  /** Subscribe to change notifications. */
  onChange(cb: () => void): () => void {
    this._listeners.push(cb);
    return () => {
      this._listeners = this._listeners.filter((l) => l !== cb);
    };
  }

  private _notify(): void {
    this._listeners.forEach((cb) => cb());
  }

  /** Refresh all data from the backend. */
  async refresh(sessionId?: string): Promise<void> {
    try {
      const [topology, assignment, health, hitl, pEvents] = await Promise.all([
        MeshConsoleAPI.getTopology(),
        MeshConsoleAPI.getAssignment(sessionId),
        MeshConsoleAPI.getAllHealth(),
        MeshConsoleAPI.getPendingHITL(),
        MeshConsoleAPI.getPresenceEvents(10),
      ]);
      this.topology = topology;
      this.assignment = assignment;
      this.health = health;
      this.pendingHITL = hitl.pending || [];
      this.presenceEvents = pEvents.events || [];
      this._notify();
    } catch (err) {
      console.error("[MeshConsole] refresh error:", err);
    }
  }

  /** Get health score for a device (returns 1.0 if unknown). */
  healthOf(deviceId: string): number {
    return this.health.scores?.[deviceId]?.total_score ?? 1.0;
  }

  /** Check whether a device is the primary body. */
  isPrimary(deviceId: string): boolean {
    return this.assignment?.primary_body?.device_id === deviceId;
  }
}

// ============================================================================
// renderMeshConsole — lightweight DOM renderer
// ============================================================================

/**
 * Mount a minimal Manifest Mesh Console into *container*.
 *
 * Renders:
 *   - Primary body (highlighted)
 *   - Secondary bodies (list)
 *   - Health scores per device
 *   - Active roles badges
 *   - Pending HITL requests (approve / reject buttons)
 *   - Recent presence-projection events
 *
 * @param container - DOM element to mount into
 * @param options   - Optional configuration
 */
export function renderMeshConsole(
  container: HTMLElement,
  options: { sessionId?: string; refreshIntervalMs?: number } = {}
): () => void {
  const model = new MeshTopology();
  const interval = options.refreshIntervalMs ?? 5000;

  const roleColor: Record<string, string> = {
    perception: "#4a9eff",
    action:     "#ff7a4a",
    presence:   "#7aff4a",
  };

  function scoreBar(score: number): string {
    const pct = Math.round(score * 100);
    const colour = pct >= 80 ? "#4caf50" : pct >= 50 ? "#ff9800" : "#f44336";
    return `<div style="display:inline-block;background:#222;border-radius:4px;width:80px;height:10px;vertical-align:middle">
      <div style="width:${pct}%;height:100%;background:${colour};border-radius:4px;"></div>
    </div> <small>${pct}%</small>`;
  }

  function roleBadge(role: string): string {
    const c = roleColor[role] ?? "#aaa";
    return `<span style="background:${c}22;color:${c};border:1px solid ${c};border-radius:4px;padding:1px 6px;font-size:11px;margin-right:3px">${role}</span>`;
  }

  function renderEntry(entry: BodyEntry, isPrimary: boolean, health: number): string {
    const border = isPrimary ? "2px solid #7aff4a" : "1px solid #333";
    const crown = isPrimary ? "👑 " : "";
    return `
      <div style="border:${border};border-radius:8px;padding:10px;margin:6px 0;background:#1a1a1a">
        <strong>${crown}${entry.device_id}</strong>
        ${entry.roles.map(roleBadge).join("")}
        <br/>
        <small>Session: ${entry.session_id ?? "—"}</small>
        &nbsp;|&nbsp;
        <small>Health: ${scoreBar(health)}</small>
        <br/>
        <small>Body score: ${entry.body_score.toFixed(2)}</small>
      </div>`;
  }

  function renderHITL(req: HITLRequest): string {
    return `
      <div style="border:1px solid #ff9800;border-radius:8px;padding:10px;margin:6px 0;background:#1a1a1a">
        <strong>⚠ ${req.action}</strong>
        <span style="float:right;font-size:11px;color:#ff9800">${req.is_high_risk ? "HIGH RISK" : "low risk"}</span>
        <br/><small>Request ID: ${req.request_id}</small>
        <br/>
        <button data-hitl-approve="${req.request_id}"
          style="margin-top:6px;padding:4px 12px;background:#4caf50;color:#fff;border:none;border-radius:4px;cursor:pointer">
          ✔ Approve
        </button>
        <button data-hitl-reject="${req.request_id}"
          style="margin-left:6px;padding:4px 12px;background:#f44336;color:#fff;border:none;border-radius:4px;cursor:pointer">
          ✘ Reject
        </button>
      </div>`;
  }

  function renderPresenceEvent(ev: ProjectionEvent): string {
    const ts = new Date(ev.projected_at * 1000).toLocaleTimeString();
    return `<li><small>${ts}</small> → <strong>${ev.device_id}</strong> intensity=${ev.intensity.toFixed(2)} [${ev.roles.join(", ")}]</li>`;
  }

  function render(): void {
    const { topology, assignment, pendingHITL, presenceEvents } = model;

    const primaryId = assignment?.primary_body?.device_id;
    const entries = topology.entries;

    const deviceHtml = entries.length === 0
      ? "<p style='color:#666'>No devices in Body Mesh. Trigger allocation first.</p>"
      : entries.map((e) => renderEntry(e, e.device_id === primaryId, model.healthOf(e.device_id))).join("");

    const hitlHtml = pendingHITL.length === 0
      ? "<p style='color:#666'>No pending HITL requests.</p>"
      : pendingHITL.map(renderHITL).join("");

    const presenceHtml = presenceEvents.length === 0
      ? "<li style='color:#666'>No recent projection events.</li>"
      : presenceEvents.map(renderPresenceEvent).join("");

    container.innerHTML = `
      <div style="font-family:monospace;color:#eee;max-width:900px;padding:16px">
        <h2 style="color:#7aff4a">🌐 Manifest Mesh Console</h2>
        <p style="color:#888">Devices: ${topology.total} | Session: ${assignment?.session_id ?? "all"}</p>

        <button id="mesh-refresh-btn"
          style="padding:6px 16px;background:#333;color:#eee;border:1px solid #555;border-radius:6px;cursor:pointer;margin-bottom:12px">
          ↺ Refresh
        </button>
        <button id="mesh-allocate-btn"
          style="padding:6px 16px;background:#333;color:#eee;border:1px solid #555;border-radius:6px;cursor:pointer;margin-bottom:12px;margin-left:8px">
          ⚙ Allocate Roles
        </button>

        <h3 style="color:#4a9eff">Body Mesh Devices</h3>
        ${deviceHtml}

        <h3 style="color:#ff9800">⚠ Pending HITL Requests</h3>
        ${hitlHtml}

        <h3 style="color:#7aff4a">Recent Presence Projections</h3>
        <ul style="color:#aaa;font-size:12px">
          ${presenceHtml}
        </ul>
      </div>`;

    // Wire up refresh / allocate buttons
    container.querySelector("#mesh-refresh-btn")?.addEventListener("click", () => {
      model.refresh(options.sessionId);
    });
    container.querySelector("#mesh-allocate-btn")?.addEventListener("click", async () => {
      await MeshConsoleAPI.allocate(options.sessionId);
      model.refresh(options.sessionId);
    });

    // Wire up HITL approve/reject buttons
    container.querySelectorAll("[data-hitl-approve]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const reqId = (btn as HTMLElement).dataset.hitlApprove!;
        await MeshConsoleAPI.submitHITLDecision(reqId, true);
        model.refresh(options.sessionId);
      });
    });
    container.querySelectorAll("[data-hitl-reject]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const reqId = (btn as HTMLElement).dataset.hitlReject!;
        await MeshConsoleAPI.submitHITLDecision(reqId, false, "rejected by user");
        model.refresh(options.sessionId);
      });
    });
  }

  // Initial render (empty) then async data load
  render();
  model.onChange(render);
  model.refresh(options.sessionId);

  // Auto-refresh
  const timer = setInterval(() => model.refresh(options.sessionId), interval);

  // Return cleanup function
  return () => {
    clearInterval(timer);
    model.onChange(() => {}); // detach
    container.innerHTML = "";
  };
}
