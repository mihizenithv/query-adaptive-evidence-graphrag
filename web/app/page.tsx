"use client";

import { ChangeEvent, PointerEvent, useCallback, useMemo, useRef, useState } from "react";

type Node = { id:string; type:string; label:string; confidence:number; community_id:string|null; evidence_ids:string[]; x:number; y:number };
type Edge = { id:string; source:string; target:string; type:string; confidence:number; evidence_ids:string[]; extraction_method:string };
type Evidence = { id:string; chunk_id:string; page:number|null; section_path:string[]; text:string };
type Graph = { nodes:Node[]; edges:Edge[]; evidence:Evidence[]; documents:Record<string, unknown>[]; total_nodes?:number; total_edges?:number; rendered_nodes?:number; rendered_edges?:number };
type Result = { answer:string; retrieval_mode:string; confidence:number; evidence:{chunk_id:string;page:number|null;text:string}[]; decision:{graph_utility:number;reasons:string[]}; trace:{step:string;status:string;detail:string;node_ids?:string[];edge_ids?:string[]}[]; node_ids:string[]; edge_ids:string[] };
type Transform = { x:number; y:number; k:number };

// The local FastAPI service uses 8001 so it remains usable when a common dev
// process already reserves 8000. Override this through NEXT_PUBLIC_API_URL.
const API = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8001";

function badgeClass(value:string) { return value.includes("graph") ? "badge graph" : value === "hybrid_text" ? "badge text" : "badge"; }

function GraphCanvas({ graph, selected, highlighted, transform, onTransform, onSelect }:{graph:Graph; selected:string|null; highlighted:Set<string>; transform:Transform; onTransform:(next:Transform)=>void; onSelect:(id:string)=>void}) {
  const byId = useMemo(() => new Map(graph.nodes.map(n => [n.id,n])), [graph.nodes]);
  const drag = useRef<{x:number;y:number;tx:number;ty:number}|null>(null);
  const zoom = (delta:number) => onTransform({...transform, k:Math.max(.45,Math.min(2.8,transform.k+delta))});
  const onPointerDown = (event:PointerEvent<SVGSVGElement>) => { event.currentTarget.setPointerCapture(event.pointerId); drag.current={x:event.clientX,y:event.clientY,tx:transform.x,ty:transform.y}; };
  const onPointerMove = (event:PointerEvent<SVGSVGElement>) => { if(!drag.current)return; onTransform({...transform,x:drag.current.tx+(event.clientX-drag.current.x),y:drag.current.ty+(event.clientY-drag.current.y)}); };
  const onPointerUp = () => { drag.current=null; };
  return <svg className="canvas" viewBox="0 0 900 650" role="img" aria-label="Evidence graph visualization" onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp} onWheel={event=>{event.preventDefault();zoom(event.deltaY<0?.1:-.1)}}>
    <g transform={`translate(${transform.x} ${transform.y}) scale(${transform.k})`}>
      {graph.edges.map(edge => { const a=byId.get(edge.source), b=byId.get(edge.target); if(!a||!b)return null; const hot=highlighted.has(edge.id); return <g key={edge.id} opacity={hot?1:.42}><line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={hot?"#73b7a2":"#53606b"} strokeWidth={hot?3:1.2} strokeDasharray={edge.type === "RELATED_TO" ? "5 5" : undefined}/><text x={(a.x+b.x)/2} y={(a.y+b.y)/2-5} fill="#8b98a5" fontSize="9" textAnchor="middle">{edge.type}</text></g> })}
      {graph.nodes.map(node => { const hot=highlighted.has(node.id), active=selected===node.id; return <g key={node.id} transform={`translate(${node.x},${node.y})`} tabIndex={0} role="button" aria-label={`Select ${node.label}`} onClick={event=>{event.stopPropagation();onSelect(node.id)}} onKeyDown={e=>{if(e.key==="Enter")onSelect(node.id)}}><circle r={active?25:hot?22:18} fill={node.type==="Entity"?"#24483f":"#1b252e"} stroke={active?"#f0d18c":hot?"#73b7a2":"#52606c"} strokeWidth={active?3:1.5}/><text textAnchor="middle" y={3} fill="#e8edf2" fontSize="10">{node.label.slice(0,15)}</text></g> })}
    </g>
  </svg>;
}

export default function Home() {
  const [graph,setGraph]=useState<Graph>({nodes:[],edges:[],evidence:[],documents:[]});
  const [selected,setSelected]=useState<string|null>(null); const [highlighted,setHighlighted]=useState<Set<string>>(new Set()); const [transform,setTransform]=useState<Transform>({x:0,y:0,k:1});
  const [query,setQuery]=useState(""); const [result,setResult]=useState<Result|null>(null); const [busy,setBusy]=useState(false); const [message,setMessage]=useState("Upload a document to begin.");
  const selectedNode=graph.nodes.find(n=>n.id===selected); const selectedEvidence=selectedNode?.evidence_ids.map(id=>graph.evidence.find(e=>e.id===id)).filter(Boolean) as Evidence[]|undefined;
  const upload=useCallback(async (event:ChangeEvent<HTMLInputElement>)=>{const file=event.target.files?.[0];if(!file)return;setBusy(true);setMessage("Indexing document…");const form=new FormData();form.append("file",file);try{const response=await fetch(`${API}/api/documents/upload`,{method:"POST",body:form});if(!response.ok)throw new Error(await response.text());const data=await response.json();setGraph(data.graph);setMessage(`${data.document.chunk_count} chunks indexed with provenance.`)}catch(error){setMessage(`Indexing failed: ${String(error)}`)}finally{setBusy(false)}},[]);
  const ask=useCallback(async()=>{if(!query.trim())return;setBusy(true);try{const response=await fetch(`${API}/api/query`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({query})});if(!response.ok)throw new Error(await response.text());const data:Result=await response.json();setResult(data);const ids=new Set([...data.node_ids,...data.edge_ids]);setHighlighted(ids)}catch(error){setMessage(`Query failed: ${String(error)}`)}finally{setBusy(false)}},[query]);
  const focusTrace=(item:Result["trace"][number])=>setHighlighted(new Set([...(item.node_ids??[]),...(item.edge_ids??[])]));
  return <main className="app-shell">
    <header className="topbar"><div><div className="eyebrow">EVIDENCE GRAPH WORKSTATION</div><h1>Query-Adaptive GraphRAG</h1></div><label className="upload"><input type="file" accept=".pdf,.docx,.txt" onChange={upload} disabled={busy}/>{busy?"WORKING":"UPLOAD DOCUMENT"}</label></header>
    <div className="statusbar"><span className="status-dot"/> {message}<span className="status-meta">{graph.rendered_nodes ?? graph.nodes.length} shown / {graph.total_nodes ?? graph.nodes.length} nodes · {graph.rendered_edges ?? graph.edges.length} shown / {graph.total_edges ?? graph.edges.length} edges · {graph.evidence.length} evidence objects</span></div>
    <section className="workspace">
      <div className="graph-panel"><div className="panel-header"><div><span className="eyebrow">GRAPH CANVAS</span><h2>Source topology</h2></div><div className="controls"><button onClick={() => setTransform(t => ({...t,k:Math.min(2.8,t.k+.15)}))} aria-label="Zoom in">+</button><button onClick={() => setTransform(t => ({...t,k:Math.max(.45,t.k-.15)}))} aria-label="Zoom out">−</button><button onClick={()=>setTransform({x:0,y:0,k:1})}>Fit</button><button onClick={()=>setHighlighted(new Set())}>Clear highlight</button><button onClick={()=>setSelected(null)}>Reset selection</button></div></div><GraphCanvas graph={graph} selected={selected} highlighted={highlighted} transform={transform} onTransform={setTransform} onSelect={setSelected}/><div className="legend"><span><i className="dot entity"/> entity</span><span><i className="dot chunk"/> source chunk</span><span><i className="line"/> evidence relation</span><span className="mono">zoom {Math.round(transform.k*100)}% · drag to move · wheel to zoom</span></div></div>
      <aside className="side-panel">
        <div className="section"><div className="eyebrow">CONTEXT</div><h2>{selectedNode?selectedNode.label:"No selection"}</h2>{selectedNode?<><div className="kv"><span>Type</span><b>{selectedNode.type}</b><span>Confidence</span><b>{Math.round(selectedNode.confidence*100)}%</b><span>ID</span><b className="mono small">{selectedNode.id}</b></div><div className="evidence-list">{selectedEvidence?.map(ev=><article key={ev.id}><div className="eyebrow">PAGE {ev.page??"—"} · {ev.chunk_id}</div><p>{ev.text}</p></article>)}</div></>:<p className="muted">Select a graph object to inspect its source evidence, confidence, and stable identity.</p>}</div>
        <div className="section answer-section">
          <div className="eyebrow">QUERY</div>
          <div className="query-row"><input value={query} onChange={e=>setQuery(e.target.value)} onKeyDown={e=>{if(e.key==="Enter")ask()}} placeholder="Ask about the indexed evidence…"/><button className="primary" onClick={ask} disabled={busy}>ASK</button></div>
          {result ? <>
            <div className="decision"><div><span className="eyebrow">RETRIEVAL STRATEGY</span><div className={badgeClass(result.retrieval_mode)}>{result.retrieval_mode.replace("_"," ")}</div></div><div className="utility"><span>graph utility</span><b>{result.decision.graph_utility}</b></div></div>
            <ul className="reasons">{result.decision.reasons.map(reason=><li key={reason}>{reason}</li>)}</ul>
            <p className="answer">{result.answer}</p>
            <div className="eyebrow">CITATIONS · {result.confidence} CONFIDENCE</div>
            {result.evidence.map(ev=><div className="citation" key={ev.chunk_id}>p.{ev.page??"—"} · {ev.chunk_id}<br/><span>{ev.text.slice(0,140)}…</span></div>)}
          </> : null}
        </div>
        <div className="section trace"><div className="eyebrow">RETRIEVAL TRACE</div>{result?.trace.map(item=><button className="trace-item" key={item.step} onClick={()=>focusTrace(item)}><span className="trace-index">✓</span><span><b>{item.step}</b><small>{item.detail}</small></span></button>) ?? <p className="muted">The actual query pipeline will appear here after a question is answered.</p>}</div>
      </aside>
    </section>
  </main>;
}
