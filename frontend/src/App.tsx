import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity, AlertTriangle, ArrowUpRight, BadgeCheck, Bell, BriefcaseBusiness,
  Building2, ChevronDown, CircleHelp, Database, Download, FileClock, Fingerprint,
  GitBranch, Globe2, LayoutDashboard, LockKeyhole, Menu, Plus, RefreshCw, Search,
  ShieldCheck, Sparkles, Workflow, X,
} from "lucide-react";
import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

type Institution = { id: string; name: string; synthetic: number; status: string };
type Signal = {
  id: string; external_signal_id: string; institution_id: string; from_institution_id: string;
  from_account_ref: string; to_institution_id: string; to_account_ref: string; amount: string;
  currency: string; channel: string; occurred_at: string; synthetic: boolean;
};
type Alert = {
  id: string; account_node: string; engine: string; score: number; status: string;
  explanation: { reasons: string[]; matched_signal_ids: string[]; limitations: string; synthetic?: boolean };
  created_at: string;
};
type Investigation = {
  id: string; title: string; summary: string; status: string; priority: string;
  institution_id?: string; assignee?: string; created_at: string; updated_at: string;
  events: { event_type: string; body: string; created_at: string }[];
};
type GeoObservation = {
  id: string; account_ref: string; location_label: string; latitude: number; longitude: number;
  occurred_at: string; synthetic: boolean;
};
type NetworkData = { nodes: { id: string; risk_indicator: number; in_degree: number; out_degree: number; reasons: string[] }[]; edges: { from: string; to: string; signal_id: string }[]; account_metrics: { risk_indicator: number; reasons: string[] } | null };
type ModelRun = { id: string; model_name: string; dataset_name: string; created_at: string; selected: number };
type ModelMetric = {
  samples: number; fraud_count: number; fraud_prevalence: number; threshold: number; precision: number; recall: number;
  f1: number; average_precision: number; roc_auc: number; confusion_matrix: {
    true_negative: number; false_positive: number; false_negative: number; true_positive: number;
  }; false_positive_rate: number; false_negative_rate: number; top_1_percent_precision: number; top_k: number;
};
type ModelEvaluation = {
  selected_model: string; split_method: string; split_sizes: Record<string, number>;
  split_class_counts: Record<string, Record<string, number>>;
  metrics: Record<string, { validation: ModelMetric; test: ModelMetric }>;
  dataset_features: string[];
  selected_threshold: number; feature_importance: { name: string; importance: number }[];
  limitations: string[];
};
type ModelPrediction = {
  prediction: number; risk_score: number; threshold: number; score_type: string;
  global_feature_importance: { name: string; importance: number }[];
  limitations: string[];
};
type View = "overview" | "signals" | "alerts" | "investigations" | "network" | "geo" | "models" | "audit";

const navigation: { id: View; label: string; icon: typeof LayoutDashboard }[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "signals", label: "Transaction intelligence", icon: Activity },
  { id: "network", label: "Network tracing", icon: GitBranch },
  { id: "geo", label: "Geo intelligence", icon: Globe2 },
  { id: "investigations", label: "Investigations", icon: BriefcaseBusiness },
  { id: "alerts", label: "Alert center", icon: AlertTriangle },
  { id: "models", label: "Model intelligence", icon: Sparkles },
  { id: "audit", label: "Audit log", icon: FileClock },
];

const money = (value: string | number) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(Number(value));
const shortTime = (value: string) => new Date(value).toLocaleString();

async function request<T>(path: string, key: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": key,
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.message ?? `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

function App() {
  const [view, setView] = useState<View>("overview");
  const [apiKey] = useState(() => localStorage.getItem("scamtrace-api-key") || "scamtrace-local-demo-key");
  const [signals, setSignals] = useState<Signal[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [cases, setCases] = useState<Investigation[]>([]);
  const [institutions, setInstitutions] = useState<Institution[]>([]);
  const [models, setModels] = useState<ModelRun[]>([]);
  const [geo, setGeo] = useState<{ label: string; observations: GeoObservation[]; indicators: { account_ref: string; distance_km: number; reasons: string[] }[] } | null>(null);
  const [network, setNetwork] = useState<NetworkData | null>(null);
  const [account, setAccount] = useState("northstar:NS-VICTIM");
  const [search, setSearch] = useState("");
  const [institutionFilter, setInstitutionFilter] = useState("all");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [selectedSignalId, setSelectedSignalId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [toast, setToast] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [caseDialog, setCaseDialog] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [signalResult, alertResult, caseResult, institutionResult, modelResult] = await Promise.all([
        request<{ items: Signal[] }>("/api/v1/signals?limit=500", apiKey),
        request<{ items: Alert[] }>("/api/v1/alerts?limit=200", apiKey),
        request<Investigation[]>("/api/v1/cases", apiKey),
        request<Institution[]>("/api/v1/institutions", apiKey),
        request<ModelRun[]>("/api/v1/models", apiKey),
      ]);
      setSignals(signalResult.items);
      setAlerts(alertResult.items);
      setCases(caseResult);
      setInstitutions(institutionResult);
      setModels(modelResult);
      setGeo(await request("/api/v1/geo/demo", apiKey));
      setLastUpdated(new Date());
      localStorage.setItem("scamtrace-api-key", apiKey);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load application data.");
    } finally {
      setLoading(false);
    }
  }, [apiKey]);

  useEffect(() => { void refresh(); }, [refresh]);

  const notify = (message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(""), 3500);
  };

  const filteredSignals = useMemo(() => signals.filter((signal) => {
    const query = search.toLowerCase();
    const matchesSearch = !query || [
      signal.id, signal.external_signal_id, signal.from_account_ref, signal.to_account_ref,
      signal.from_institution_id, signal.to_institution_id, signal.channel,
    ].some((value) => value.toLowerCase().includes(query));
    const matchesInstitution = institutionFilter === "all" ||
      signal.institution_id === institutionFilter ||
      signal.from_institution_id === institutionFilter ||
      signal.to_institution_id === institutionFilter;
    const matchesSource = sourceFilter === "all" ||
      (sourceFilter === "synthetic" ? signal.synthetic : !signal.synthetic);
    return matchesSearch && matchesInstitution && matchesSource;
  }), [signals, search, institutionFilter, sourceFilter]);

  const chartData = useMemo(() => {
    const byDay = new Map<string, number>();
    signals.forEach((signal) => {
      const day = new Date(signal.occurred_at).toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
      byDay.set(day, (byDay.get(day) || 0) + Number(signal.amount));
    });
    return Array.from(byDay, ([day, amount]) => ({ day, amount }));
  }, [signals]);

  const actOnAlert = async (alert: Alert, action: "acknowledge" | "escalate" | "dismiss") => {
    const reason = action === "dismiss" ? window.prompt("Provide a reason for dismissal:") : undefined;
    if (action === "dismiss" && !reason) return;
    try {
      await request(`/api/v1/alerts/${alert.id}/actions`, apiKey, {
        method: "POST", body: JSON.stringify({ action, reason }),
      });
      await refresh();
      notify(`Alert ${action === "acknowledge" ? "acknowledged" : `${action}d`}.`);
    } catch (reasonError) {
      setError(reasonError instanceof Error ? reasonError.message : "Alert action failed.");
    }
  };

  const openCaseFromAlert = async (alert: Alert) => {
    try {
      await request(`/api/v1/alerts/${alert.id}/cases`, apiKey, { method: "POST" });
      await refresh();
      notify("Investigation case created.");
    } catch (reasonError) {
      setError(reasonError instanceof Error ? reasonError.message : "Case creation failed.");
    }
  };

  const changeCaseStatus = async (item: Investigation, status: string) => {
    try {
      await request(`/api/v1/cases/${item.id}`, apiKey, { method: "PATCH", body: JSON.stringify({ status }) });
      await refresh();
      notify("Investigation status updated.");
    } catch (reasonError) {
      setError(reasonError instanceof Error ? reasonError.message : "Case update failed.");
    }
  };

  const exportSignals = () => {
    const columns = ["external_signal_id", "institution_id", "from_institution_id", "from_account_ref", "to_institution_id", "to_account_ref", "amount", "currency", "channel", "occurred_at", "synthetic"];
    const escapeCsv = (value: unknown) => {
      const text = String(value ?? "");
      const safe = /^[=+\-@\t\r]/.test(text) ? `'${text}` : text;
      return `"${safe.replaceAll('"', '""')}"`;
    };
    const csv = [columns.join(","), ...filteredSignals.map((signal) =>
      columns.map((column) => escapeCsv(signal[column as keyof Signal])).join(","),
    )].join("\n");
    const link = document.createElement("a");
    const objectUrl = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    link.href = objectUrl;
    link.download = "scamtrace-signals.csv";
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
    notify(`Exported ${filteredSignals.length} signal${filteredSignals.length === 1 ? "" : "s"}.`);
  };

  const current = navigation.find((item) => item.id === view)!;
  const CurrentIcon = current.icon;
  const filteredAlerts = alerts.filter((item) => statusFilter === "all" || item.status === statusFilter);

  return (
    <div className="app-shell">
      <aside className={`sidebar ${menuOpen ? "sidebar-open" : ""}`}>
        <div className="brand"><div className="brand-mark"><ShieldCheck size={20} /></div><div><b>SCAMTRACE</b><span>FINANCIAL INTELLIGENCE</span></div></div>
        <div className="workspace-label">WORKSPACE</div>
        <div className="org-switch"><div className="org-icon"><Building2 size={17} /></div><div><b>Investigation unit</b><small>Demo environment</small></div></div>
        <nav className="nav-list" aria-label="Main navigation">
          {navigation.map((item) => {
            const Icon = item.icon;
            return <button key={item.id} className={`nav-item ${view === item.id ? "active" : ""}`} onClick={() => { setView(item.id); setMenuOpen(false); }}>
              <Icon size={17} strokeWidth={1.8} /><span>{item.label}</span>
              {item.id === "alerts" && alerts.some((alert) => alert.status === "new") && <i className="nav-dot" />}
            </button>;
          })}
        </nav>
        <div className="sidebar-bottom">
          <div className="connection-card"><span className="pulse-dot" /><div><b>Local API</b><small>{loading ? "Syncing records" : error ? "Needs attention" : "Connected"}</small></div><button title="Refresh data" onClick={() => void refresh()}><RefreshCw size={14} /></button></div>
          <div className="user-card"><div className="avatar">DA</div><div><b>Demo administrator</b><small>Local development role</small></div></div>
        </div>
      </aside>
      {menuOpen && <button className="mobile-backdrop" aria-label="Close navigation" onClick={() => setMenuOpen(false)} />}
      <main className="main-area">
        <header className="topbar">
          <button className="mobile-menu" onClick={() => setMenuOpen(!menuOpen)} aria-label="Toggle menu"><Menu size={19} /></button>
          <div className="breadcrumb"><span>Intelligence</span><span className="slash">/</span><b><CurrentIcon size={15} />{current.label}</b></div>
          <div className="top-actions">
            <label className="searchbox"><Search size={15} /><input aria-label="Search transaction signals" placeholder="Search signals or accounts" value={search} onChange={(event) => setSearch(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") setView("signals"); }} /></label>
            <span className="environment-pill"><span /> SIMULATED</span>
            <button className="icon-button" title="Open alert center" aria-label="Open alert center" onClick={() => setView("alerts")}><Bell size={17} />{alerts.some((alert) => alert.status === "new") && <i />}</button>
            <div className="avatar top-avatar" title="Local development role">DA</div>
          </div>
        </header>

        <section className="page-content">
          <div className="page-heading">
            <div><div className="eyebrow"><LockKeyhole size={12} /> LOCAL DEMONSTRATION · SYSTEM ADMIN</div><h1>{current.label}</h1><p>Connect permitted signals and review explainable leads. Indicators are not verified findings.</p></div>
            <div className="heading-actions"><button className="secondary-button" onClick={() => void refresh()}><RefreshCw size={15} /> Refresh</button>
              {view === "signals" && <button className="primary-button" onClick={exportSignals}><Download size={15} /> Export CSV</button>}
              {view === "investigations" && <button className="primary-button" onClick={() => setCaseDialog(true)}><Plus size={16} /> New case</button>}
            </div>
          </div>

          {error && <div className="error-banner"><AlertTriangle size={17} /><span>{error}</span><button onClick={() => setError("")} aria-label="Dismiss error"><X size={15} /></button></div>}
          {loading && <div className="loading-bar"><span /></div>}

          {view === "overview" && <Overview signals={signals} alerts={alerts} cases={cases} institutions={institutions} chartData={chartData} setView={setView} />}
          {view === "signals" && <SignalsPage signals={filteredSignals} search={search} setSearch={setSearch} institutions={institutions} institutionFilter={institutionFilter} setInstitutionFilter={setInstitutionFilter} sourceFilter={sourceFilter} setSourceFilter={setSourceFilter} alerts={alerts} selectedId={selectedSignalId} setSelectedId={setSelectedSignalId} traceAccount={(node) => { setAccount(node); setNetwork(null); setView("network"); }} />}
          {view === "alerts" && <AlertsPage alerts={filteredAlerts} statusFilter={statusFilter} setStatusFilter={setStatusFilter} actOnAlert={actOnAlert} openCase={openCaseFromAlert} reviewSignals={(alert) => { const signalId = alert.explanation.matched_signal_ids[0] || ""; setSearch(signalId); setSelectedSignalId(signalId); setView("signals"); }} traceAccount={(alert) => { setAccount(alert.account_node); setNetwork(null); setView("network"); }} />}
          {view === "investigations" && <InvestigationsPage cases={cases} changeStatus={changeCaseStatus} />}
          {view === "network" && <NetworkPage account={account} setAccount={setAccount} network={network} setNetwork={setNetwork} apiKey={apiKey} setError={setError} signals={signals} />}
          {view === "geo" && <GeoPage geo={geo} />}
          {view === "models" && <ModelsPage models={models} apiKey={apiKey} />}
          {view === "audit" && <AuditPage apiKey={apiKey} setError={setError} />}
        </section>
        <footer className="footer"><span>SCAMTRACE AI <i>·</i> Local prototype <i>·</i> SQLite · API v1{lastUpdated && <> <i>·</i> Updated {lastUpdated.toLocaleTimeString()}</>}</span><span><CircleHelp size={13} /> Human review required <i>·</i> No payment controls</span></footer>
      </main>
      {caseDialog && <NewCaseDialog apiKey={apiKey} institutions={institutions} close={() => setCaseDialog(false)} saved={async () => { setCaseDialog(false); await refresh(); notify("Investigation created."); }} fail={(message) => setError(message)} />}
      {toast && <div className="toast"><BadgeCheck size={17} />{toast}</div>}
    </div>
  );
}

function Metric({ label, value, note, icon: Icon, tone = "green" }: { label: string; value: string; note: string; icon: typeof Activity; tone?: string }) {
  return <article className="metric-card"><div className="metric-top"><span>{label}</span><div className={`metric-icon ${tone}`}><Icon size={17} /></div></div><strong>{value}</strong><small>{note}</small></article>;
}

function Overview({ signals, alerts, cases, institutions, chartData, setView }: {
  signals: Signal[]; alerts: Alert[]; cases: Investigation[]; institutions: Institution[];
  chartData: { day: string; amount: number }[]; setView: (view: View) => void;
}) {
  const newAlerts = alerts.filter((alert) => alert.status === "new");
  const activeCases = cases.filter((item) => !["closed", "resolved"].includes(item.status));
  const highRiskAccounts = new Set(alerts.filter((alert) => alert.score >= 70).map((alert) => alert.account_node)).size;
  return <>
    <div className="metrics-grid">
      <Metric label="Signals monitored" value={signals.length.toLocaleString()} note={`${signals.filter((signal) => signal.synthetic).length} explicitly synthetic`} icon={Activity} />
      <Metric label="Open alerts" value={newAlerts.length.toLocaleString()} note="Awaiting investigator review" icon={AlertTriangle} tone="amber" />
      <Metric label="Active investigations" value={activeCases.length.toLocaleString()} note={`${cases.length} total case records`} icon={BriefcaseBusiness} tone="blue" />
      <Metric label="Priority accounts" value={highRiskAccounts.toLocaleString()} note="Rule-based indicator ≥ 70" icon={Fingerprint} tone="red" />
      <Metric label="Demo institutions" value={institutions.length.toLocaleString()} note="Simulated connectors only" icon={Building2} tone="slate" />
    </div>
    <div className="dashboard-grid">
      <article className="panel activity-panel">
        <div className="panel-heading"><div><h2>Transaction activity</h2><p>Observed signal value by event date · INR</p></div><button className="text-button" onClick={() => setView("signals")}>View signals <ArrowUpRight size={14} /></button></div>
        {chartData.length ? <div className="chart-wrap"><ResponsiveContainer width="100%" height="100%"><BarChart data={chartData} margin={{ top: 10, right: 12, left: -12, bottom: 0 }}>
          <CartesianGrid stroke="#202d3b" vertical={false} /><XAxis dataKey="day" tick={{ fill: "#8292a3", fontSize: 11 }} axisLine={false} tickLine={false} /><YAxis tick={{ fill: "#8292a3", fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip contentStyle={{ background: "#111a24", border: "1px solid #283747", borderRadius: 9, color: "#e6edf5" }} formatter={(value) => money(Number(value))} /><Bar dataKey="amount" fill="#54cda4" radius={[4, 4, 0, 0]} maxBarSize={42} />
        </BarChart></ResponsiveContainer></div> : <EmptyState label="No transaction signals available" />}
        <div className="chart-legend"><span><i className="legend-dot green-dot" /> Signal amount</span><span>Values are sourced from permitted demo records</span></div>
      </article>
      <article className="panel alert-panel">
        <div className="panel-heading"><div><h2>Priority alert queue</h2><p>Explainable network indicators</p></div><button className="text-button" onClick={() => setView("alerts")}>All alerts <ArrowUpRight size={14} /></button></div>
        <div className="alert-list">{alerts.slice(0, 5).map((alert) => <div className="alert-row" key={alert.id}><div className={`severity ${alert.score >= 70 ? "critical" : "elevated"}`}><AlertTriangle size={15} /></div><div className="alert-copy"><b>{alert.account_node}</b><span>{alert.explanation.reasons[0] || "Network indicator matched"}</span><small>{shortTime(alert.created_at)}</small></div><span className="score-pill">{Math.round(alert.score)}<small>/100</small></span></div>)}{!alerts.length && <EmptyState label="No alerts to review" />}</div>
      </article>
      <article className="panel recent-panel">
        <div className="panel-heading"><div><h2>Recent transaction signals</h2><p>Latest signal records visible in this workspace</p></div><button className="text-button" onClick={() => setView("signals")}>Open ledger <ArrowUpRight size={14} /></button></div>
        <div className="table-scroll"><table><thead><tr><th>Signal</th><th>Route</th><th>Amount</th><th>Time</th></tr></thead><tbody>{signals.slice(-6).reverse().map((signal) => <tr key={signal.id}><td><b>{signal.external_signal_id}</b>{signal.synthetic && <span className="mini-tag">SYN</span>}</td><td>{signal.from_account_ref}<span className="route-arrow">→</span>{signal.to_account_ref}</td><td className="amount">{money(signal.amount)}</td><td>{new Date(signal.occurred_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}</td></tr>)}</tbody></table></div>
      </article>
      <article className="panel integration-panel">
        <div className="panel-heading"><div><h2>Institution connectors</h2><p>Fictional institutions in the local demo</p></div><span className="status-tag"><span /> Simulated</span></div>
        <div className="institution-list">{institutions.map((institution) => <div className="institution-row" key={institution.id}><div className="institution-logo">{institution.name.slice(0, 1)}</div><div><b>{institution.name}</b><small>Demo institution · No live connection</small></div><span className="demo-status">DEMO</span></div>)}</div>
        <div className="integration-note"><Database size={15} /> Signals are locally stored in SQLite. No bank is connected.</div>
      </article>
    </div>
  </>;
}

function SignalsPage({ signals, search, setSearch, institutions, institutionFilter, setInstitutionFilter, sourceFilter, setSourceFilter, alerts, selectedId, setSelectedId, traceAccount }: {
  signals: Signal[]; search: string; setSearch: (value: string) => void; institutions: Institution[];
  institutionFilter: string; setInstitutionFilter: (value: string) => void;
  sourceFilter: string; setSourceFilter: (value: string) => void; alerts: Alert[];
  selectedId: string; setSelectedId: (value: string) => void;
  traceAccount: (node: string) => void;
}) {
  const selected = signals.find((signal) => signal.id === selectedId);
  const relatedAlerts = selected ? alerts.filter((alert) => alert.explanation.matched_signal_ids.includes(selected.id)) : [];
  return <div className="signal-layout"><section className="panel full-panel"><div className="panel-heading"><div><h2>Signal ledger</h2><p>Minimized transaction signals · synthetic status shown per record</p></div><div className="table-tools"><label className="searchbox"><Search size={14} /><input aria-label="Filter signals" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Filter signals" /></label><select className="select-control" aria-label="Filter by institution" value={institutionFilter} onChange={(event) => setInstitutionFilter(event.target.value)}><option value="all">All institutions</option>{institutions.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select><select className="select-control source-filter" aria-label="Filter by data source" value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)}><option value="all">All data</option><option value="synthetic">Synthetic</option><option value="ingested">Ingested</option></select></div></div>
    <div className="table-scroll"><table><thead><tr><th>Signal ID</th><th>Origin</th><th>Destination</th><th>Amount</th><th>Channel</th><th>Timestamp</th><th>Source</th></tr></thead><tbody>{signals.map((signal) => <tr key={signal.id} onClick={() => setSelectedId(signal.id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") setSelectedId(signal.id); }} tabIndex={0} className="click-row" aria-label={`Inspect ${signal.external_signal_id}`}><td><b>{signal.external_signal_id}</b></td><td><span className="institution-code">{signal.from_institution_id}</span><br />{signal.from_account_ref}</td><td><span className="institution-code">{signal.to_institution_id}</span><br />{signal.to_account_ref}</td><td className="amount">{money(signal.amount)}</td><td>{signal.channel}</td><td>{shortTime(signal.occurred_at)}</td><td><span className={signal.synthetic ? "tag-synthetic" : "tag-authorized"}>{signal.synthetic ? "Synthetic" : "Ingested"}</span></td></tr>)}</tbody></table>
      {!signals.length && <EmptyState label="No matching signal records" />}
    </div><div className="table-foot"><span>Showing {signals.length} signal{signals.length === 1 ? "" : "s"}</span><span><LockKeyhole size={13} /> Account references are pseudonymous labels</span></div>
  </section>
  {selected && <aside className="panel signal-detail"><button className="detail-close" onClick={() => setSelectedId("")} aria-label="Close signal detail"><X size={15} /></button><div className="eyebrow">TRANSACTION SIGNAL</div><h2>{selected.external_signal_id}</h2><p>{selected.synthetic ? "Synthetic demonstration record" : "Ingested signal"}</p><dl><div><dt>Origin</dt><dd>{selected.from_institution_id} · {selected.from_account_ref}</dd></div><div><dt>Destination</dt><dd>{selected.to_institution_id} · {selected.to_account_ref}</dd></div><div><dt>Amount and channel</dt><dd>{money(selected.amount)} · {selected.channel}</dd></div><div><dt>Occurred</dt><dd>{shortTime(selected.occurred_at)}</dd></div></dl><h3>Linked investigation alerts</h3>{relatedAlerts.length ? relatedAlerts.map((alert) => <div className="signal-evidence" key={alert.id}><span className="score-pill">{Math.round(alert.score)}<small>/100</small></span><ul>{alert.explanation.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul><button className="secondary-button" onClick={() => traceAccount(alert.account_node)}><GitBranch size={14} /> Trace {alert.account_node}</button></div>) : <p>No alert references this signal. This does not imply the signal is cleared.</p>}</aside>}</div>;
}

function AlertsPage({ alerts, statusFilter, setStatusFilter, actOnAlert, openCase, reviewSignals, traceAccount }: {
  alerts: Alert[]; statusFilter: string; setStatusFilter: (value: string) => void;
  actOnAlert: (alert: Alert, action: "acknowledge" | "escalate" | "dismiss") => void;
  openCase: (alert: Alert) => void;
  reviewSignals: (alert: Alert) => void;
  traceAccount: (alert: Alert) => void;
}) {
  return <section className="panel full-panel"><div className="panel-heading"><div><h2>Explainable alert queue</h2><p>Rule-based risk indicators are leads, not verified fraud determinations</p></div><select className="select-control" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="all">All statuses</option><option value="new">New</option><option value="acknowledged">Acknowledged</option><option value="escalated">Escalated</option><option value="dismissed">Dismissed</option></select></div>
    <div className="alert-cards">{alerts.map((alert) => <article className="queue-card" key={alert.id}><div className="queue-card-top"><div className={`severity ${alert.score >= 70 ? "critical" : "elevated"}`}><AlertTriangle size={16} /></div><div className="queue-account"><b>{alert.account_node}</b><span>{alert.engine.replace("_", " ")} · {shortTime(alert.created_at)}</span></div><div className="score-pill">{Math.round(alert.score)}<small>/100</small></div><span className={`case-status ${alert.status}`}>{alert.status.replace("_", " ")}</span></div><div className="explanation-box"><b>Matched evidence</b><ul>{alert.explanation.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul><small>{alert.explanation.matched_signal_ids.length} related signal references · {alert.explanation.synthetic ? "Synthetic demo" : "Ingested signals"}</small><p>{alert.explanation.limitations}</p></div>{alert.status !== "dismissed" && <div className="alert-actions"><button className="secondary-button" disabled={alert.status === "acknowledged"} onClick={() => actOnAlert(alert, "acknowledge")}><BadgeCheck size={14} /> {alert.status === "acknowledged" ? "Acknowledged" : "Acknowledge"}</button><button className="secondary-button" disabled={alert.status === "escalated"} onClick={() => actOnAlert(alert, "escalate")}><ArrowUpRight size={14} /> {alert.status === "escalated" ? "Escalated" : "Escalate"}</button><button className="secondary-button" onClick={() => reviewSignals(alert)}><Activity size={14} /> Review signals</button><button className="secondary-button" onClick={() => traceAccount(alert)}><GitBranch size={14} /> Trace network</button><button className="secondary-button" onClick={() => openCase(alert)}><BriefcaseBusiness size={14} /> Create case</button><button className="quiet-button" onClick={() => actOnAlert(alert, "dismiss")}>Dismiss</button></div>}</article>)}{!alerts.length && <EmptyState label="No alerts match this filter" />}</div>
  </section>;
}

function InvestigationsPage({ cases, changeStatus }: { cases: Investigation[]; changeStatus: (item: Investigation, status: string) => void }) {
  const [selected, setSelected] = useState<string>("");
  const current = cases.find((item) => item.id === selected);
  return <div className="investigation-layout"><section className="panel full-panel"><div className="panel-heading"><div><h2>Investigation workbench</h2><p>Human-reviewed cases and recorded activity</p></div><span className="count-pill">{cases.length} cases</span></div><div className="table-scroll"><table><thead><tr><th>Case</th><th>Priority</th><th>Assignee</th><th>Status</th><th>Updated</th><th /></tr></thead><tbody>{cases.map((item) => <tr key={item.id} onClick={() => setSelected(item.id)} className="click-row"><td><b>{item.title}</b><small className="sub-cell">{item.id.slice(0, 8)} · {item.institution_id || "Cross-institution"}</small></td><td><span className={`priority ${item.priority}`}>{item.priority}</span></td><td>{item.assignee || "Unassigned"}</td><td><span className={`case-status ${item.status}`}>{item.status.replace("_", " ")}</span></td><td>{shortTime(item.updated_at)}</td><td><ChevronDown size={15} /></td></tr>)}</tbody></table></div>{!cases.length && <EmptyState label="No investigations yet. Create a case from the alert center." />}</section>
    {current && <section className="panel case-detail"><button className="detail-close" onClick={() => setSelected("")}><X size={15} /></button><div className="eyebrow">CASE DETAIL</div><h2>{current.title}</h2><p>{current.summary || "No summary provided."}</p><div className="case-meta"><span>Priority <b>{current.priority}</b></span><span>Status <b>{current.status.replace("_", " ")}</b></span><span>Assignee <b>{current.assignee || "Unassigned"}</b></span></div><label className="field-label">Update status<select className="select-control" value={current.status} onChange={(event) => changeStatus(current, event.target.value)}><option value="new">New</option><option value="under_review">Under review</option><option value="escalated">Escalated</option><option value="resolved">Resolved</option><option value="closed">Closed</option></select></label><h3>Investigation timeline</h3><div className="timeline">{current.events.map((event, index) => <div className="timeline-item" key={`${event.created_at}-${index}`}><i /><div><b>{event.event_type.replace("_", " ")}</b><p>{event.body}</p><small>{shortTime(event.created_at)}</small></div></div>)}</div></section>}
  </div>;
}

function NetworkPage({ account, setAccount, network, setNetwork, apiKey, setError, signals }: {
  account: string; setAccount: (value: string) => void; network: NetworkData | null;
  setNetwork: (value: NetworkData) => void; apiKey: string; setError: (value: string) => void; signals: Signal[];
}) {
  const accounts = useMemo(() => Array.from(new Set(signals.flatMap((signal) => [
    `${signal.from_institution_id}:${signal.from_account_ref}`,
    `${signal.to_institution_id}:${signal.to_account_ref}`,
  ]))).sort(), [signals]);
  const traceAccount = async (accountNode: string) => {
    setAccount(accountNode);
    try {
      setNetwork(await request(`/api/v1/accounts/${encodeURIComponent(accountNode)}/network?depth=3`, apiKey));
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Network trace failed.");
    }
  };
  const trace = async (event?: React.FormEvent) => {
    event?.preventDefault();
    try { setNetwork(await request(`/api/v1/accounts/${encodeURIComponent(account)}/network?depth=3`, apiKey)); setError(""); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Network trace failed."); }
  };
  useEffect(() => { if (!network && signals.length) void trace(); }, [network, signals.length]);
  return <div className="network-layout"><section className="panel network-panel"><div className="panel-heading"><div><h2>Directed transaction trace</h2><p>Connected accounts and transfer relationships · synthetic demo signals</p></div><Workflow size={19} className="muted-icon" /></div><form className="trace-search" onSubmit={trace}><label className="searchbox"><Search size={15} /><input list="network-account-options" value={account} onChange={(event) => setAccount(event.target.value)} placeholder="institution:account reference" /></label><button className="primary-button">Trace network</button></form>
    <datalist id="network-account-options">{accounts.map((node) => <option value={node} key={node} />)}</datalist>
    {network?.nodes.length ? <><div className="graph-canvas"><svg viewBox="0 0 760 340" role="img" aria-label="Transaction network diagram">{network.edges.map((edge, index) => {
      const fromIndex = network.nodes.findIndex((node) => node.id === edge.from);
      const toIndex = network.nodes.findIndex((node) => node.id === edge.to);
      const columns = Math.max(2, Math.ceil(Math.sqrt(network.nodes.length)));
      const point = (n: number) => ({ x: 95 + (n % columns) * (560 / Math.max(1, columns - 1)), y: 65 + Math.floor(n / columns) * 190 / Math.max(1, Math.ceil(network.nodes.length / columns)) });
      const a = point(fromIndex); const b = point(toIndex);
      return <g key={`${edge.signal_id}-${index}`}><line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#3b5365" strokeWidth="2" markerEnd="url(#arrow)" /><text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 7} className="edge-label">{edge.signal_id}</text></g>;
    })}<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="#3b5365" /></marker></defs>{network.nodes.map((node, index) => { const columns = Math.max(2, Math.ceil(Math.sqrt(network.nodes.length))); const x = 95 + (index % columns) * (560 / Math.max(1, columns - 1)); const y = 65 + Math.floor(index / columns) * 190 / Math.max(1, Math.ceil(network.nodes.length / columns)); return <g key={node.id} className="network-node" role="button" tabIndex={0} aria-label={`Trace connected activity from ${node.id}, indicator ${node.risk_indicator}`} onClick={() => void traceAccount(node.id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") void traceAccount(node.id); }}><title>{node.id} · Rule indicator {node.risk_indicator}/100 · {node.reasons.join("; ")}</title><circle cx={x} cy={y} r="23" fill={node.risk_indicator >= 45 ? "#482c36" : "#173a36"} stroke={node.risk_indicator >= 45 ? "#e77e83" : "#54cda4"} strokeWidth="2" /><text x={x} y={y + 4} textAnchor="middle" className="node-score">{node.risk_indicator}</text><text x={x} y={y + 39} textAnchor="middle" className="node-label">{node.id.split(":").slice(-1)[0]}</text><text x={x} y={y + 50} textAnchor="middle" className="node-institution">{node.id.split(":")[0]}</text></g>; })}</svg></div>
      <div className="network-summary"><span><i className="legend-dot green-dot" /> Lower indicator</span><span><i className="legend-dot red-dot" /> Review indicator ≥ 45</span><span>Directed arrows show movement · Hover or select a node for evidence</span><span>{network.nodes.length} accounts · {network.edges.length} signals</span></div>
      <div className="table-scroll"><table><thead><tr><th>Account</th><th>In</th><th>Out</th><th>Indicator</th><th>Evidence</th></tr></thead><tbody>{network.nodes.map((node) => <tr key={node.id}><td><b>{node.id}</b></td><td>{node.in_degree}</td><td>{node.out_degree}</td><td><span className="score-pill">{node.risk_indicator}<small>/100</small></span></td><td>{node.reasons.join("; ")}</td></tr>)}</tbody></table></div>
    </> : <EmptyState label="Enter an account reference and trace its connected activity" />}
  </section><aside className="panel network-aside"><div className="eyebrow">EXPLAINABLE INDICATORS</div><h2>Network evidence</h2>{network?.account_metrics ? <><div className="large-score">{network.account_metrics.risk_indicator}<small>/100</small></div><p>Rule-based prioritization indicator. Not a calibrated probability or verified finding.</p><ul>{network.account_metrics.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></> : <p>Select an account to see configured graph evidence and related transfer indicators.</p>}<div className="disclaimer"><ShieldCheck size={15} /> All graph records in the included fixture are synthetic.</div></aside></div>;
}

function GeoPage({ geo }: { geo: { label: string; observations: GeoObservation[]; indicators: { account_ref: string; distance_km: number; reasons: string[] }[] } | null }) {
  const points = geo?.observations || [];
  const minLat = Math.min(...points.map((point) => point.latitude), 0);
  const maxLat = Math.max(...points.map((point) => point.latitude), 1);
  const minLon = Math.min(...points.map((point) => point.longitude), 0);
  const maxLon = Math.max(...points.map((point) => point.longitude), 1);
  const xy = (point: GeoObservation) => ({
    x: 38 + ((point.longitude - minLon) / Math.max(1, maxLon - minLon)) * 560,
    y: 250 - ((point.latitude - minLat) / Math.max(1, maxLat - minLat)) * 200,
  });
  return <div className="geo-layout"><section className="panel geo-panel"><div className="panel-heading"><div><h2>Geographic signal demonstration</h2><p>Illustrative coordinate plot · not a real-world map</p></div><span className="synthetic-banner"><Globe2 size={14} /> SYNTHETIC LOCATIONS</span></div><div className="geo-warning"><AlertTriangle size={16} /><span>{geo?.label || "Coordinates are a separate synthetic fixture and are not linked to ULB transactions or real customers."}</span></div><div className="geo-plot"><svg viewBox="0 0 640 290" aria-label="Plot of synthetic geographic points">{[0, 1, 2, 3, 4].map((line) => <g key={line}><line x1="30" x2="610" y1={35 + line * 52} y2={35 + line * 52} stroke="#1b2a37" /><line y1="25" y2="265" x1={38 + line * 140} x2={38 + line * 140} stroke="#1b2a37" /></g>)}{points.map((point) => { const pos = xy(point); return <g key={point.id}><circle cx={pos.x} cy={pos.y} r="8" fill="#54cda4" stroke="#d3fff0" strokeWidth="2" /><text x={pos.x + 12} y={pos.y - 10} className="geo-label">{point.location_label}</text></g>; })}</svg></div><div className="geo-legend"><span><i className="legend-dot green-dot" /> Synthetic observation</span><span>Coordinates are arbitrary demonstration metadata</span></div></section>
    <section className="panel full-panel"><div className="panel-heading"><div><h2>Illustrative movement indicators</h2><p>Distance calculated from the separate synthetic location fixture</p></div><span className="count-pill">{geo?.indicators.length || 0} comparisons</span></div><div className="table-scroll"><table><thead><tr><th>Account</th><th>Distance</th><th>Indicator</th><th>Evidence</th></tr></thead><tbody>{geo?.indicators.map((item, index) => <tr key={`${item.account_ref}-${index}`}><td>{item.account_ref}</td><td>{item.distance_km.toLocaleString()} km</td><td>{item.reasons.length ? <span className="priority high">Review</span> : <span className="case-status resolved">No configured rule</span>}</td><td>{item.reasons.join(", ") || "No configured displacement threshold matched."}</td></tr>)}</tbody></table></div><p className="fine-print">Synthetic coordinates do not represent any customer, institution, or actual transaction. Geographic indicators are review leads only.</p></section>
  </div>;
}

function ModelsPage({ models, apiKey }: { models: ModelRun[]; apiKey: string }) {
  const [evaluation, setEvaluation] = useState<ModelEvaluation | null>(null);
  const [prediction, setPrediction] = useState<ModelPrediction | null>(null);
  const [predicting, setPredicting] = useState(false);
  const [predictionError, setPredictionError] = useState("");
  const selectedModel = models.find((model) => model.selected);
  useEffect(() => {
    if (!selectedModel) { setEvaluation(null); return; }
    let active = true;
    setEvaluation(null);
    setPrediction(null);
    setPredictionError("");
    request<{ evaluation: ModelEvaluation }>(`/api/v1/models/${selectedModel.id}`, apiKey)
      .then((result) => { if (active) setEvaluation(result.evaluation); })
      .catch((reason) => {
        if (active) setPredictionError(reason instanceof Error ? reason.message : "Model evaluation is unavailable.");
      });
    return () => { active = false; };
  }, [apiKey, selectedModel?.id]);
  const runSmokePrediction = async () => {
    if (!evaluation) return;
    setPredicting(true);
    setPredictionError("");
    try {
      const features = Object.fromEntries(evaluation.dataset_features.map((name) => [name, 0]));
      const result = await request<ModelPrediction>("/api/v1/predictions", apiKey, {
        method: "POST",
        body: JSON.stringify({ features }),
      });
      setPrediction(result);
    } catch (reason) {
      setPredictionError(reason instanceof Error ? reason.message : "Model inference failed.");
    } finally {
      setPredicting(false);
    }
  };
  return <div className="models-layout"><section className="panel full-panel"><div className="panel-heading"><div><h2>Model registry</h2><p>Only persisted training runs are shown. Metrics are loaded from the evaluation report.</p></div><span className="status-tag"><Database size={14} /> ULB / Worldline track</span></div>{models.length ? <><div className="model-grid">{models.map((model) => <article className="model-card" key={model.id}><div className="model-symbol"><Sparkles size={18} /></div><span className={model.selected ? "tag-authorized" : "case-status"}>{model.selected ? "Selected" : "Archived"}</span><h3>{model.model_name.replaceAll("_", " ")}</h3><p>{model.dataset_name}</p><div className="model-meta"><span>Trained {shortTime(model.created_at)}</span><b>{model.id.slice(0, 8)}</b></div></article>)}</div>
    {evaluation && <><div className="evaluation-heading"><div><h3>Held-out test comparison</h3><p>{evaluation.split_method}</p></div><span className="tag-authorized">Selected by validation Average Precision</span></div><div className="table-scroll"><table><thead><tr><th>Model</th><th>Precision</th><th>Recall</th><th>F1</th><th>PR-AUC (Avg. Precision)</th><th>ROC-AUC</th><th>Top 1% Precision</th></tr></thead><tbody>{Object.entries(evaluation.metrics).map(([name, result]) => <tr key={name}><td><b>{name.replaceAll("_", " ")}</b>{name === evaluation.selected_model && <span className="mini-tag">SELECTED</span>}</td><td>{(result.test.precision * 100).toFixed(2)}%</td><td>{(result.test.recall * 100).toFixed(2)}%</td><td>{(result.test.f1 * 100).toFixed(2)}%</td><td>{result.test.average_precision.toFixed(4)}</td><td>{result.test.roc_auc.toFixed(4)}</td><td>{(result.test.top_1_percent_precision * 100).toFixed(2)}% ({result.test.top_k})</td></tr>)}</tbody></table></div><div className="confusion-grid">{Object.entries(evaluation.metrics).map(([name, result]) => <article className="confusion-card" key={name}><b>{name.replaceAll("_", " ")} · test confusion matrix</b><div><span>TN <strong>{result.test.confusion_matrix.true_negative.toLocaleString()}</strong></span><span>FP <strong>{result.test.confusion_matrix.false_positive.toLocaleString()}</strong></span><span>FN <strong>{result.test.confusion_matrix.false_negative.toLocaleString()}</strong></span><span>TP <strong>{result.test.confusion_matrix.true_positive.toLocaleString()}</strong></span></div><small>{result.test.samples.toLocaleString()} test records · threshold {result.test.threshold.toFixed(6)}</small></article>)}</div><p className="fine-print">Measured from this run's held-out split ({evaluation.split_sizes.test.toLocaleString()} records). Scores are not calibrated fraud probabilities. The dataset has no bank identity, account graph, or GPS and is not validation for partner-bank transfers.</p>
      <div className="inference-panel"><div><div className="eyebrow">INFERENCE SMOKE TEST</div><h3>Model prediction</h3><p>Run a zero-valued ULB feature vector to verify loading, preprocessing order, and inference. This is a synthetic test input, not a transaction.</p><button className="secondary-button" disabled={predicting} onClick={() => void runSmokePrediction()}><Sparkles size={14} />{predicting ? "Scoring…" : "Run synthetic smoke input"}</button></div>{prediction && <div className="prediction-result"><span className={prediction.prediction ? "priority high" : "case-status resolved"}>{prediction.prediction ? "Above threshold" : "Below threshold"}</span><strong>{prediction.risk_score.toFixed(4)}<small>score</small></strong><span>Decision threshold {prediction.threshold.toFixed(4)}</span><p>{prediction.score_type}</p><b>Global model feature importance</b><small>{prediction.global_feature_importance.map((feature) => feature.name).join(" · ")}</small></div>}</div>
      {predictionError && <div className="error-banner" role="alert"><AlertTriangle size={15} />{predictionError}</div>}
      {prediction && <ul className="prediction-limitations">{prediction.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul>}
      </>}
    </> : <div className="empty-model"><div className="model-symbol"><Sparkles size={20} /></div><h3>No model run registered</h3><p>Run the documented ULB training command to create actual evaluation metrics and a versioned artifact.</p><code>python -m scripts.train_ulb</code></div>}</section>
    <section className="panel model-caveat"><ShieldCheck size={17} /><div><b>Dataset scope and limitations</b><ul>{evaluation?.limitations.map((limitation) => <li key={limitation}>{limitation}</li>) || <li>ULB is an anonymized transaction benchmark. It has no account graph, bank identity, or GPS. Its model is not validated for partner-bank transfers.</li>}</ul></div></section>
  </div>;
}

function AuditPage({ apiKey, setError }: { apiKey: string; setError: (value: string) => void }) {
  const [rows, setRows] = useState<{ id: string; actor: string; role: string; action: string; resource_type: string; resource_id?: string; outcome: string; created_at: string }[]>([]);
  useEffect(() => { request<typeof rows>("/api/v1/audit?limit=200", apiKey).then(setRows).catch((reason) => setError(reason instanceof Error ? reason.message : "Audit records unavailable.")); }, [apiKey, setError]);
  return <section className="panel full-panel"><div className="panel-heading"><div><h2>Activity audit</h2><p>Recorded authenticated reads and actions · secrets and raw payloads are excluded</p></div><span className="count-pill">{rows.length} events</span></div><div className="table-scroll"><table><thead><tr><th>Timestamp</th><th>Actor</th><th>Role</th><th>Action</th><th>Resource</th><th>Outcome</th></tr></thead><tbody>{rows.map((row) => <tr key={row.id}><td>{shortTime(row.created_at)}</td><td>{row.actor}</td><td>{row.role}</td><td><b>{row.action}</b></td><td>{row.resource_type} · {row.resource_id?.slice(0, 8) || "—"}</td><td><span className="case-status resolved">{row.outcome}</span></td></tr>)}</tbody></table>{!rows.length && <EmptyState label="No audit events have been recorded yet" />}</div></section>;
}

function NewCaseDialog({ apiKey, institutions, close, saved, fail }: {
  apiKey: string; institutions: Institution[]; close: () => void; saved: () => Promise<void>; fail: (message: string) => void;
}) {
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [priority, setPriority] = useState("medium");
  const [institution, setInstitution] = useState("");
  const [saving, setSaving] = useState(false);
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    try {
      await request("/api/v1/cases", apiKey, { method: "POST", body: JSON.stringify({ title, summary, priority, institution_id: institution || null }) });
      await saved();
    } catch (reason) {
      fail(reason instanceof Error ? reason.message : "Could not create case.");
    } finally {
      setSaving(false);
    }
  };
  return <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) close(); }}><form className="dialog" onSubmit={submit}><div className="dialog-heading"><div><div className="eyebrow">INVESTIGATION WORKFLOW</div><h2>Create a case</h2></div><button type="button" className="icon-button" onClick={close}><X size={17} /></button></div><label>Case title<input required minLength={3} maxLength={200} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Describe the investigation lead" /></label><label>Summary<textarea maxLength={5000} value={summary} onChange={(event) => setSummary(event.target.value)} placeholder="Record the initial context for human review" /></label><div className="form-row"><label>Priority<select value={priority} onChange={(event) => setPriority(event.target.value)}><option value="critical">Critical</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select></label><label>Institution<select value={institution} onChange={(event) => setInstitution(event.target.value)}><option value="">Cross-institution</option>{institutions.map((item) => <option value={item.id} key={item.id}>{item.name} (demo)</option>)}</select></label></div><div className="dialog-actions"><button type="button" className="secondary-button" onClick={close}>Cancel</button><button className="primary-button" disabled={saving}>{saving ? "Saving..." : "Create investigation"}</button></div><small className="fine-print">Case records are persisted locally. Decisions remain with authorized investigators.</small></form></div>;
}

function EmptyState({ label }: { label: string }) {
  return <div className="empty-state"><div><Activity size={18} /></div><span>{label}</span></div>;
}

export default App;
