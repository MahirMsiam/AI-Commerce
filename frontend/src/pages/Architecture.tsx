import { Card } from '../components/ui'

type BoxProps = { x: number; y: number; w: number; h: number; title: string; sub?: string; tone?: 'blue' | 'grey' | 'violet' }
const TONE = { blue: ['#eaf2fc', '#2a78d6'], grey: ['#f3f2ef', '#8a8984'], violet: ['#efedfb', '#6250d6'] }

function Box({ x, y, w, h, title, sub, tone = 'grey' }: BoxProps) {
  const [fill, stroke] = TONE[tone]
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx={10} fill={fill} stroke={stroke} strokeWidth={1.5} />
      <text x={x + w / 2} y={y + (sub ? h / 2 - 4 : h / 2 + 5)} textAnchor="middle" fontSize={14} fontWeight={600} fill="#0b0b0b">{title}</text>
      {sub && <text x={x + w / 2} y={y + h / 2 + 15} textAnchor="middle" fontSize={11} fill="#52514e">{sub}</text>}
    </g>
  )
}

const Arrow = ({ x1, y1, x2, y2 }: { x1: number; y1: number; x2: number; y2: number }) => (
  <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="#8a8984" strokeWidth={1.5} markerEnd="url(#arrow)" />
)

const LEFT = [['Distributor & retailer portal', 'orders · AI suggested order'], ['Management dashboard', 'KPIs · forecasts · alerts'], ['Sales staff (1,500)', 'mobile app · Phase 2']]
const RIGHT = [['SAP ERP / MRP', 'OData · BAPI · system of record'], ['Custom in-house systems', 'secondary sales, HR…'], ['Email server', 'IMAP / SMTP'], ['Data warehouse', 'history for forecasting']]

const ROADMAP = [
  ['Pilot · 3 months', ['1 division, 3–5 distributors', 'Ask your data + stock alerts on SAP extracts', 'Inbox agent on one shared mailbox', 'Success measures agreed up front']],
  ['Scale', ['All 8 divisions, live SAP OData integration', 'Real email, approval workflow in SAP', 'On-prem GPU server, larger open model', 'Full tool-calling agent']],
  ['Factories', ['Predictive maintenance on plant sensor data', 'Forecast → MRP / S&OP planning', 'Same on-prem AI platform']],
] as const

export default function Architecture() {
  return (
    <div className="space-y-4">
      <Card title="Where this plugs into SMC's systems">
        <svg viewBox="0 0 1000 420" className="w-full" role="img"
          aria-label="Distributor portal, dashboard and staff apps connect through an API and integration layer to SAP ERP, custom systems, email and a data warehouse. A local LLM server runs on-premise. Everything stays in-country.">
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" fill="#8a8984" />
            </marker>
          </defs>
          <rect x={8} y={8} width={984} height={404} rx={16} fill="none" stroke="#1baf7a" strokeDasharray="6 5" strokeWidth={1.5} />
          <text x={24} y={32} fontSize={12} fill="#137a55" fontWeight={600}>On-premise / in-country · Personal Data Protection Ordinance 2025</text>
          {LEFT.map(([t, s], i) => <Box key={t} x={30} y={60 + i * 110} w={220} h={70} title={t} sub={s} tone="blue" />)}
          <Box x={340} y={150} w={240} h={110} title="API & integration layer" sub="this demo: FastAPI · /api/erp mock" tone="violet" />
          {RIGHT.map(([t, s], i) => <Box key={t} x={680} y={50 + i * 85} w={290} h={62} title={t} sub={s} />)}
          <Box x={340} y={320} w={240} h={70} title="Local LLM server" sub="open-source model · Ollama · no API cost" tone="violet" />
          {LEFT.map((_, i) => <Arrow key={i} x1={250} y1={95 + i * 110} x2={338} y2={205} />)}
          {RIGHT.map((_, i) => <Arrow key={i} x1={582} y1={205} x2={678} y2={81 + i * 85} />)}
          <Arrow x1={460} y1={262} x2={460} y2={318} />
        </svg>
        <p className="mt-2 text-sm text-stone-600">
          In this prototype the SAP box is a mock service with SAP-style fields (VBELN, KUNNR, MATNR, KLIMK), email is a sample inbox,
          and the warehouse is a local SQLite file. SAP stays the system of record; the AI layer reads from it and writes only drafts for human approval.
        </p>
      </Card>

      <div className="grid gap-4 md:grid-cols-3">
        {ROADMAP.map(([title, items], i) => (
          <Card key={title} title={<><span className="mr-2 rounded-full bg-stone-900 px-2 text-xs text-white">{i + 1}</span>{title}</>}>
            <ul className="list-disc space-y-1 pl-5 text-sm text-stone-700">{items.map((it) => <li key={it}>{it}</li>)}</ul>
          </Card>
        ))}
      </div>
    </div>
  )
}
