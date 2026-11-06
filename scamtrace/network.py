from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Any

import networkx as nx


def node_id(institution_id: str, account_ref: str) -> str:
    return f"{institution_id}:{account_ref}"


def analyze_signals(signals: list[dict[str, Any]], rapid_window_seconds: int = 600) -> dict[str, Any]:
    graph = nx.MultiDiGraph()
    normalized: list[dict[str, Any]] = []
    account_institutions: dict[str, set[str]] = {}
    for signal in signals:
        source = node_id(signal["from_institution_id"], signal["from_account_ref"])
        target = node_id(signal["to_institution_id"], signal["to_account_ref"])
        item = {**signal, "source_node": source, "target_node": target}
        normalized.append(item)
        graph.add_edge(source, target, key=signal["id"], signal_id=signal["id"])
        account_institutions.setdefault(source, set()).update(
            (signal["from_institution_id"], signal["to_institution_id"])
        )
        account_institutions.setdefault(target, set()).update(
            (signal["from_institution_id"], signal["to_institution_id"])
        )

    metrics: dict[str, dict[str, Any]] = {}
    for account in graph.nodes:
        incoming = [row for row in normalized if row["target_node"] == account]
        outgoing = [row for row in normalized if row["source_node"] == account]
        score = 0
        reasons: list[str] = []
        if len(outgoing) >= 2:
            score += 15
            reasons.append("Multiple outgoing transfers")
        if incoming and outgoing:
            score += 15
            reasons.append("Receives and forwards funds")
        quick = any(
            0 <= (
                datetime.fromisoformat(out_row["occurred_at"])
                - datetime.fromisoformat(in_row["occurred_at"])
            ).total_seconds() <= rapid_window_seconds
            for in_row in incoming
            for out_row in outgoing
        )
        if quick:
            score += 35
            reasons.append(f"Funds forwarded within {rapid_window_seconds // 60} minutes")
        involved = incoming + outgoing
        if involved and max(float(row["amount"]) for row in involved) >= 20000:
            score += 20
            reasons.append("Involved in a high-value transfer")
        institutions = account_institutions.get(account, set())
        if len(institutions) >= 3:
            score += 15
            reasons.append("Connected activity spans three institutions")
        metrics[account] = {
            "account_node": account,
            "risk_indicator": min(score, 100),
            "reasons": reasons or ["No configured network indicator matched"],
            "in_degree": len(incoming),
            "out_degree": len(outgoing),
            "incoming_amount": round(sum(float(row["amount"]) for row in incoming), 2),
            "outgoing_amount": round(sum(float(row["amount"]) for row in outgoing), 2),
            "connected_accounts": len(set(graph.predecessors(account)) | set(graph.successors(account))),
            "institution_count": len(institutions),
            "signal_ids": [row["id"] for row in involved],
        }
    return {"graph": graph, "metrics": metrics, "signals": normalized}


def trace_network(
    signals: list[dict[str, Any]], account_node: str, max_depth: int = 2, max_nodes: int = 200
) -> dict[str, Any]:
    analysis = analyze_signals(signals)
    graph: nx.MultiDiGraph = analysis["graph"]
    if account_node not in graph:
        return {"nodes": [], "edges": [], "account_metrics": None}
    visited = {account_node}
    queue = deque([(account_node, 0)])
    while queue and len(visited) < max_nodes:
        current, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for neighbor in set(graph.predecessors(current)) | set(graph.successors(current)):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, depth + 1))
                if len(visited) >= max_nodes:
                    break
    edges = []
    for source, target, key, data in graph.edges(keys=True, data=True):
        if source in visited and target in visited:
            edges.append({"from": source, "to": target, "signal_id": key})
    return {
        "nodes": [
            {"id": account, **analysis["metrics"][account]}
            for account in sorted(visited)
        ],
        "edges": edges,
        "account_metrics": analysis["metrics"][account_node],
    }
