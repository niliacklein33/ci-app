import React, { useEffect, useMemo, useState } from "react";
import {
  Bell, BellRing, Search, Mail, Newspaper, Sparkles, ArrowUpRight,
  Shield, ShieldCheck, Copy, ClipboardCheck, TriangleAlert, Layers,
  Settings2, Send, CheckCircle2, Globe, Database, RefreshCcw
} from "lucide-react";

// ------------------- Config -------------------
const COMPETITORS = ["ISNetworld", "Avetta", "KPA Flex", "VendorPM", "Gartner Peer Insights"];

// Seed data shows only in local dev when the JSON hasn’t been generated yet.
const seedInsights = [
  { id: "i1", competitor: "ISNetworld", title: "ISN announces enhanced Workers' Comp analytics for CA/AU", summary: "Adds exemption tracking, historical WC data, and improved reporting; shifts customer conversations to trend analysis over doc uploads.", sourceName: "Business Wire", sourceUrl: "https://www.businesswire.com/newsroom", date: new Date(Date.now() - 1000*60*60*6).toISOString(), tags: ["Product","Workers' Comp","Analytics"] },
  { id: "i2", competitor: "Avetta", title: "Avetta previews AskAva 2.0 AI for contractor Q&A", summary: "Natural-language search across compliance artifacts; promises lower support volume and faster onboarding for suppliers.", sourceName: "Company Blog", sourceUrl: "https://example.com/avetta-blog", date: new Date(Date.now() - 1000*60*60*26).toISOString(), tags: ["AI","Search","Onboarding"] },
  { id: "i3", competitor: "KPA Flex", title: "KPA bundles SDS + Contractor Mgmt in platform license", summary: "Unified pricing (up to 50 users) emphasizes configurability and mobile access; consultative sales motion.", sourceName: "Analyst Note", sourceUrl: "https://example.com/analyst-memo", date: new Date(Date.now() - 1000*60*60*50).toISOString(), tags: ["Pricing","Bundling","Sales Motion"] },
  { id: "i4", competitor: "VendorPM", title: "VendorPM expands e-bidding integrations with procurement suites", summary: "Tighter RFP sync enables eligibility checks at invite/award and pushes compliance statuses into buyer workflows.", sourceName: "Press Release", sourceUrl: "https://example.com/press", date: new Date(Date.now() - 1000*60*90).toISOString(), tags: ["Integration","E-bidding"] },
  { id: "i5", competitor: "ISNetworld", title: "CultureSight adds safety climate trend breakdowns", summary: "Perception surveys surface SIF-leading indicators by site and trade for targeted interventions.", sourceName: "Product Notes", sourceUrl: "https://example.com/isn-culturesight", date: new Date(Date.now() - 1000*60*12).toISOString(), tags: ["Safety","Survey","SIF"] },
];

// ------------------- Helpers -------------------
function inferSeverity(tags: string[]){
  const t = tags.join(" ").toLowerCase();
  if(/pricing|price|bundle/.test(t)) return "critical";
  if(/ai|e-bidding|e-bidding|integration/.test(t)) return "watch";
  return "info";
}

function toBattleCard(insight: { competitor: string; title: string; sourceName: string; date: string; sourceUrl: string; tags: string[]; }){
  const base = {
    headline: `${insight.competitor}: ${insight.title}`,
    impact: "Raises buyer expectations for analytics clarity and workflow fit.",
    proof: `Source: ${insight.sourceName} • ${new Date(insight.date).toLocaleString()}`,
    counters: [
      "Emphasize time-to-value with prebuilt scorecards & fast onboarding.",
      "Show integration depth (RFP/award, APIs, export) with demos.",
      "Publish TCO story vs. bundle pricing.",
    ],
    link: insight.sourceUrl,
    tags: insight.tags,
  };
  if (insight.tags.includes("AI")) {
    base.impact = "Shifts narrative to AI-assist; raises bar for search and self-serve answers.";
    base.counters.unshift("Demo AI explainability and guardrails for regulated buyers.");
  }
  if (insight.tags.includes("Pricing")) base.counters.unshift("Offer side-by-side TCO with transparent tiers.");
  if (insight.tags.includes("E-bidding")) base.counters.unshift("Position eligibility checks at invite/award as buyer efficiency.");
  return base;
}

function useLocalStorage<T>(key: string, initial: T): [T, React.Dispatch<React.SetStateAction<T>>]{
  const [v,setV]=useState<T>(()=>{try{const r=localStorage.getItem(key); return r?JSON.parse(r):initial;}catch{return initial as T}});
  useEffect(()=>{try{localStorage.setItem(key, JSON.stringify(v));}catch{}},[key,v]);
  return [v,setV];
}

// ------------------- App -------------------
export default function App(){
  // Live insights (from /data/insights.json in /public). Starts empty and loads on mount.
  const [insights,setInsights]=useState<any[]>([]);
  const [query,setQuery]=useState("");
  const [competitor,setCompetitor]=useState("All");
  const [from,setFrom]=useState("");
  const [to,setTo]=useState("");
  const [settings,setSettings]=useLocalStorage("ciapp_settings_v3",{notifications:false,autoIngest:true});
  const [curated,setCurated]=useLocalStorage("ciapp_curated_v3",[] as any[]);
  const [sending,setSending]=useState(false);
  const [copied,setCopied]=useState(false);
  const [loading,setLoading]=useState(true);

  // Load live JSON and refresh every 60s.
  useEffect(() => {
    let cancelled = false;
    const url = `${import.meta.env.BASE_URL}data/insights.json`;

    async function load() {
      try {
        const r = await fetch(url, { cache: "no-store" });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = await r.json();
        if (!cancelled && Array.isArray(data)) {
          setInsights(data);
        }
      } catch {
        // In dev, fall back to seeds so you see something locally
        if (import.meta.env.DEV && !cancelled) setInsights(seedInsights);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    const t = setInterval(load, 60_000); // refresh every minute
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  // Metrics
  const lastSync = insights.length? new Date(insights[0].date).toLocaleString(): "—";
  const coverage = new Set(insights.map(i=>i.competitor)).size;
  const totalSources = new Set(insights.map(i=>i.sourceName)).size;
  const totalItems = insights.length;

  // Filters
  const filtered = useMemo(()=>{
    const start = from?new Date(from).getTime():-Infinity;
    const end = to?new Date(to).getTime():Infinity;
    const q = query.trim().toLowerCase();
    return insights.filter(i=>{
      const t=new Date(i.date).getTime();
      const inRange = t>=start && t<=end;
      const byComp = competitor==="All"||i.competitor===competitor;
      const byQuery = !q || i.title?.toLowerCase().includes(q) || i.summary?.toLowerCase().includes(q) || (i.tags||[]).join(" ").toLowerCase().includes(q);
      return inRange && byComp && byQuery;
    });
  },[insights,from,to,competitor,query]);

  // Team update markdown
  const markdown = useMemo(()=>{
    const items = filtered.slice(0,8).map(i=>`- **${i.competitor}** — ${i.title}  \n  ${i.summary}  \n  Source: [${i.sourceName}](${i.sourceUrl}) • ${new Date(i.date).toLocaleString()}`);
    return `# Competitor & Market Update\n\n${new Date().toLocaleString()}\n\n${items.join("\n\n")}\n`;
  },[filtered]);

  // Actions
  function copy(text:string){navigator.clipboard.writeText(text).then(()=>{setCopied(true); setTimeout(()=>setCopied(false),1200);});}
  function enableNotifications(){ if(!("Notification" in window)) return; Notification.requestPermission().then(p=> setSettings(s=>({...s,notifications:p==="granted"}))); }
  function curate(i:any){ const c={ id:i.id, competitor:i.competitor, ...toBattleCard(i) }; setCurated(prev=>[c,...prev.filter(x=>x.id!==c.id)]); }

  // initial skeleton feel
  useEffect(()=>{ if(!loading){return} const t=setTimeout(()=>setLoading(false), 600); return ()=>clearTimeout(t);},[loading]);

  return (
    <div className="min-h-screen bg-[radial-gradient(60rem_60rem_at_80%_-10%,#E6F0FF_0%,transparent_50%),linear-gradient(#FFFFFF,#F8FAFC)] text-slate-800">
      {/* Top Bar */}
      <header className="sticky top-0 z-30 border-b border-slate-200/70 bg-white/85 backdrop-blur">
        <div className="mx-auto max-w-7xl px-4 py-3 flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-[#153A66] to-[#215FB1] shadow-sm">
            <Layers className="h-5 w-5 text-white"/>
          </div>
          <div>
            <h1 className="text-[1.1rem] font-semibold text-slate-900 tracking-tight">Competitive Intelligence</h1>
            <p className="text-xs text-slate-500">Live insights • Source-linked • Auto-updated</p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <button onClick={()=>setSettings(s=>({...s,autoIngest:!s.autoIngest}))} className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition-shadow focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-[#215FB1] ${settings.autoIngest?"border-[#C8DAFF] bg-[#ECF3FF] text-[#153A66]": "border-slate-200 text-slate-700"}`}>
              <Sparkles className="h-4 w-4"/> {settings.autoIngest?"Auto-update On":"Auto-update Off"}
            </button>
            <button onClick={enableNotifications} className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition-shadow focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-[#215FB1] ${settings.notifications?"border-[#C8DAFF] bg-[#ECF3FF] text-[#153A66]":"border-slate-200 text-slate-700"}`}>
              {settings.notifications? <BellRing className="h-4 w-4"/>:<Bell className="h-4 w-4"/>} Alerts
            </button>
            <button className="inline-flex items-center gap-2 rounded-full border border-slate-200 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-[#215FB1]"><Settings2 className="h-4 w-4"/> Settings</button>
          </div>
        </div>
      </header>

      {/* Trust Metrics */}
      <section className="border-b border-slate-200/70 bg-white/80 backdrop-blur">
        <div className="mx-auto max-w-7xl px-4 py-5 grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Metric icon={<CheckCircle2 className="h-5 w-5 text-[#215FB1]"/>} label="Coverage" value={`${coverage} competitors`} />
          <Metric icon={<Globe className="h-5 w-5 text-[#215FB1]"/>} label="Sources" value={`${totalSources} feeds`} />
          <Metric icon={<Database className="h-5 w-5 text-[#215FB1]"/>} label="Insights" value={`${totalItems} items`} />
          <Metric icon={<RefreshCcw className="h-5 w-5 text-[#215FB1]"/>} label="Last sync" value={lastSync} />
        </div>
      </section>

      {/* Controls */}
      <Controls
        query={query} setQuery={setQuery}
        competitor={competitor} setCompetitor={setCompetitor}
        from={from} setFrom={setFrom} to={to} setTo={setTo}
      />

      {/* Main */}
      <main className="mx-auto max-w-7xl px-4 py-8 grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Insights Feed */}
        <div className="lg:col-span-2">
          <h2 className="mb-4 text-lg font-semibold tracking-tight text-slate-900 flex items-center gap-2"><Newspaper className="h-5 w-5 text-[#215FB1]"/> Recent Insights</h2>
          <ul className="space-y-4">
            {(loading ? Array.from({length:3}).map((_,k)=>({id:`sk${k}`})) : filtered).map(i=> (
              <li key={i.id} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition hover:shadow-md">
                {loading ? (
                  <div className="animate-pulse space-y-3">
                    <div className="h-3 w-24 rounded bg-slate-100"/>
                    <div className="h-4 w-3/4 rounded bg-slate-100"/>
                    <div className="h-3 w-full rounded bg-slate-100"/>
                  </div>
                ) : (
                  <div className="flex items-start gap-3">
                    <div className="mt-1 h-2.5 w-2.5 flex-shrink-0 rounded-full bg-[#215FB1]"/>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-xs font-semibold uppercase tracking-wide text-[#153A66]">{i.competitor}</div>
                          <a href={i.sourceUrl} target="_blank" rel="noreferrer" className="group inline-flex items-start gap-1">
                            <h3 className="text-[15px] font-semibold leading-snug text-slate-900 group-hover:underline underline-offset-2">{i.title}</h3>
                            <ArrowUpRight className="h-4 w-4 text-[#215FB1]"/>
                          </a>
                        </div>
                        <div className="flex items-center gap-2">
                          <SeverityBadge tags={i.tags || []}/>
                          <time className="text-xs text-slate-500">{new Date(i.date).toLocaleString()}</time>
                        </div>
                      </div>
                      <p className="mt-1 text-sm text-slate-700">{i.summary}</p>
                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        <span className="rounded-full bg-[#ECF3FF] px-2.5 py-0.5 text-xs font-medium text-[#153A66] ring-1 ring-[#C8DAFF]">{i.sourceName}</span>
                        {(i.tags || []).map((t:string)=>(
                          <span key={t} className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs text-slate-700">#{t}</span>
                        ))}
                        <button onClick={()=>curate(i)} className="ml-auto inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1 text-xs text-slate-700 hover:border-[#AFC8EE] hover:text-[#153A66] focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-[#215FB1]">
                          <Shield className="h-3.5 w-3.5"/> Add to Battle Card
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>

        {/* Right rail */}
        <RightRail
          curated={curated}
          markdown={markdown}
          copied={copied}
          copy={copy}
          sending={sending}
          setSending={setSending}
        />
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-200/70 py-6">
        <div className="mx-auto max-w-7xl px-4 text-xs text-slate-500">
          Designed for confidence. Live insights are sourced from the crawler’s <code>data/insights.json</code>.
        </div>
      </footer>
    </div>
  );
}

// --------------- UI Bits ----------------
function Metric({icon, label, value}:{icon: React.ReactNode, label:string, value:string}){
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm flex items-center gap-3">
      {icon}
      <div>
        <div className="text-xs text-slate-500">{label}</div>
        <div className="text-sm font-semibold text-slate-900">{value}</div>
      </div>
    </div>
  );
}

function Controls({query,setQuery,competitor,setCompetitor,from,setFrom,to,setTo}:{query:string,setQuery:any,competitor:string,setCompetitor:any,from:string,setFrom:any,to:string,setTo:any}){
  return (
    <section className="border-b border-slate-200/70 bg-white/70 backdrop-blur">
      <div className="mx-auto max-w-7xl px-4 py-4 grid grid-cols-1 md:grid-cols-5 gap-3 items-end">
        <div className="md:col-span-2">
          <label className="text-xs font-medium text-slate-600">Search</label>
          <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 shadow-sm focus-within:ring-2 focus-within:ring-[#215FB1]/40">
            <Search className="h-4 w-4 text-slate-500"/>
            <input value={query} onChange={(e)=>setQuery(e.target.value)} placeholder="Keywords, tags, summaries…" className="w-full bg-transparent text-sm outline-none placeholder:text-slate-400"/>
          </div>
        </div>
        <div>
          <label className="text-xs font-medium text-slate-600">Competitor</label>
          <select className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-[#215FB1]/40" value={competitor} onChange={(e)=>setCompetitor(e.target.value)}>
            <option>All</option>
            {COMPETITORS.map(c=> <option key={c}>{c}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs font-medium text-slate-600">From</label>
          <input type="date" value={from} onChange={(e)=>setFrom(e.target.value)} className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-[#215FB1]/40"/>
        </div>
        <div>
          <label className="text-xs font-medium text-slate-600">To</label>
          <input type="date" value={to} onChange={(e)=>setTo(e.target.value)} className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-[#215FB1]/40"/>
        </div>
      </div>
    </section>
  );
}

function SeverityBadge({ tags }: { tags: string[] }){
  const s = inferSeverity(tags);
  if(s === "critical") return (<span className="inline-flex items-center gap-1 rounded-full bg-rose-100 px-2 py-0.5 text-[11px] font-medium text-rose-700 ring-1 ring-rose-200"><span className="h-1.5 w-1.5 rounded-full bg-rose-500"/>Critical</span>);
  if(s === "watch") return (<span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-700 ring-1 ring-amber-200"><span className="h-1.5 w-1.5 rounded-full bg-amber-500"/>Watch</span>);
  return (<span className="inline-flex items-center gap-1 rounded-full bg-sky-100 px-2 py-0.5 text-[11px] font-medium text-sky-700 ring-1 ring-sky-200"><span className="h-1.5 w-1.5 rounded-full bg-sky-500"/>Info</span>);
}

function RightRail({curated, markdown, copied, copy, sending, setSending}:{curated:any[], markdown:string, copied:boolean, copy:(t:string)=>void, sending:boolean, setSending:any}){
  return (
    <div className="space-y-8">
      {/* Battle Cards */}
      <section>
        <h2 className="mb-4 text-lg font-semibold tracking-tight text-slate-900 flex items-center gap-2"><ShieldCheck className="h-5 w-5 text-[#215FB1]"/> Battle Cards</h2>
        {curated.length===0 ? (
          <div className="rounded-2xl border border-dashed border-slate-300 p-6 text-sm text-slate-500 bg-white/70">No battle cards yet. Curate insights from the feed to populate this section.</div>
        ) : (
          <ul className="space-y-4">
            {curated.map(c=> (
              <li key={c.id} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <div className="text-xs font-semibold uppercase tracking-wide text-[#153A66]">{c.competitor}</div>
                <a href={c.link} target="_blank" rel="noreferrer" className="group inline-flex items-start gap-1">
                  <h3 className="text-[15px] font-semibold text-slate-900 group-hover:underline underline-offset-2">{c.headline}</h3>
                  <ArrowUpRight className="h-4 w-4 text-[#215FB1]"/>
                </a>
                <p className="mt-1 text-sm text-slate-700"><span className="font-medium">Impact:</span> {c.impact}</p>
                <ul className="mt-2 list-disc pl-5 text-sm text-slate-700 space-y-1">
                  {c.counters.map((ct,idx)=>(<li key={idx}>{ct}</li>))}
                </ul>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <span className="rounded-md bg-slate-50 px-2 py-0.5 text-xs text-slate-600 ring-1 ring-slate-200">{c.proof}</span>
                  {c.tags.map((t:string)=> (<span key={t} className="rounded-full bg-[#ECF3FF] px-2.5 py-0.5 text-xs font-medium text-[#153A66] ring-1 ring-[#C8DAFF]">#{t}</span>))}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Team Update */}
      <section>
        <h2 className="mb-4 text-lg font-semibold tracking-tight text-slate-900 flex items-center gap-2"><Mail className="h-5 w-5 text-[#215FB1]"/> Team Update</h2>
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <textarea className="h-40 w-full resize-none rounded-xl border border-slate-200 p-3 text-sm shadow-inner focus:outline-none focus:ring-2 focus:ring-[#215FB1]/40" value={markdown} onChange={()=>{}}/>
          <div className="mt-3 flex items-center gap-2">
            <button onClick={()=>copy(markdown)} className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-700 hover:border-[#AFC8EE] hover:text-[#153A66] focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-[#215FB1]">
              {copied? <ClipboardCheck className="h-4 w-4"/>: <Copy className="h-4 w-4"/>}
              {copied?"Copied":"Copy markdown"}
            </button>
            <button onClick={()=>{setSending(true); setTimeout(()=>setSending(false),900)}} className="inline-flex items-center gap-2 rounded-lg bg-[#153A66] px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-[#1C4E8E] focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-[#215FB1]">
              <Send className="h-4 w-4"/> {sending?"Sending…":"Send preview"}
            </button>
          </div>
          <p className="mt-2 text-xs text-slate-500">Every insight includes source link + date. Paste into Outlook/Slack.</p>
        </div>
      </section>

      {/* Alerts legend */}
      <section>
        <h2 className="mb-4 text-lg font-semibold tracking-tight text-slate-900 flex items-center gap-2"><TriangleAlert className="h-5 w-5 text-[#215FB1]"/> Alerts</h2>
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm text-sm text-slate-700">
          <p className="mb-2">Enable desktop notifications to be pinged when new insights arrive.</p>
          <ul className="grid grid-cols-3 gap-2">
            <li className="rounded-lg border border-slate-200 p-2 text-center"><span className="inline-block rounded-full bg-sky-100 px-2 py-0.5 text-xs text-sky-700">Info</span><div className="mt-1 text-xs text-slate-500">FYI mentions</div></li>
            <li className="rounded-lg border border-slate-200 p-2 text-center"><span className="inline-block rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-700">Watch</span><div className="mt-1 text-xs text-slate-500">Potential impact</div></li>
            <li className="rounded-lg border border-slate-200 p-2 text-center"><span className="inline-block rounded-full bg-rose-100 px-2 py-0.5 text-xs text-rose-700">Critical</span><div className="mt-1 text-xs text-slate-500">Immediate action</div></li>
          </ul>
        </div>
      </section>
    </div>
  );
}
