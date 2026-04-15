import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  LineChart,
  Line,
  PieChart,
  Pie,
  Cell,
  Legend,
} from 'recharts'

interface ChartData {
  type: 'bar' | 'line' | 'pie' | 'none'
  x: string
  y: string
  title: string
  data: any[]
}

const COLORS = ['#00ff88', '#00bcd4', '#ffb86c', '#ff5555', '#a277ff', '#ff79c6']

export default function ChartDisplay({ type, x, y, title, data }: ChartData) {
  if (type === 'none' || !data || data.length === 0) return null

  const renderChart = () => {
    switch (type) {
      case 'bar':
        return (
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" vertical={false} />
            <XAxis 
              dataKey={x} 
              stroke="var(--text-secondary)" 
              fontSize={12}
              tickLine={false}
              axisLine={false}
            />
            <YAxis 
              stroke="var(--text-secondary)" 
              fontSize={12}
              tickLine={false}
              axisLine={false}
              tickFormatter={(value) => typeof value === 'number' ? value.toLocaleString() : value}
            />
            <Tooltip 
              contentStyle={{ background: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: '8px' }}
              itemStyle={{ color: 'var(--accent-green)' }}
            />
            <Bar dataKey={y} fill="var(--accent-green)" radius={[4, 4, 0, 0]} barSize={40} />
          </BarChart>
        )
      case 'line':
        return (
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" vertical={false} />
            <XAxis 
              dataKey={x} 
              stroke="var(--text-secondary)" 
              fontSize={12}
              tickLine={false}
              axisLine={false}
            />
            <YAxis 
              stroke="var(--text-secondary)" 
              fontSize={12}
              tickLine={false}
              axisLine={false}
              tickFormatter={(value) => typeof value === 'number' ? value.toLocaleString() : value}
            />
            <Tooltip 
              contentStyle={{ background: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: '8px' }}
              itemStyle={{ color: 'var(--accent-cyan)' }}
            />
            <Line type="monotone" dataKey={y} stroke="var(--accent-cyan)" strokeWidth={3} dot={{ r: 4, fill: 'var(--accent-cyan)' }} activeDot={{ r: 6 }} />
          </LineChart>
        )
      case 'pie':
        return (
          <PieChart>
            <Pie
              data={data}
              dataKey={y}
              nameKey={x}
              cx="50%"
              cy="50%"
              outerRadius={80}
              label={({ name, percent }) => `${name} ${(percent as number * 100).toFixed(0)}%`}
              labelLine={false}
            >
              {data.map((_, index) => (
                <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} stroke="var(--bg-primary)" strokeWidth={2} />
              ))}
            </Pie>
            <Tooltip 
              contentStyle={{ background: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: '8px' }}
            />
            <Legend verticalAlign="bottom" height={36}/>
          </PieChart>
        )
      default:
        return null
    }
  }

  return (
    <div style={{
      background: 'var(--bg-secondary)',
      border: '1px solid var(--border-color)',
      borderRadius: '16px',
      padding: '24px',
      marginTop: '16px',
      width: '100%',
    }}>
      <h3 style={{
        fontSize: '14px',
        fontWeight: 600,
        marginBottom: '20px',
        color: 'var(--text-primary)',
        fontFamily: 'var(--font-sans)',
        display: 'flex',
        alignItems: 'center',
        gap: '8px'
      }}>
        <span style={{ 
          display: 'inline-block', 
          width: '8px', 
          height: '8px', 
          borderRadius: '50%', 
          background: type === 'line' ? 'var(--accent-cyan)' : 'var(--accent-green)' 
        }} />
        {title}
      </h3>
      <div style={{ width: '100%', height: 300 }}>
        <ResponsiveContainer width="100%" height="100%">
          {renderChart() || <div>Chart type not supported</div>}
        </ResponsiveContainer>
      </div>
    </div>
  )
}
