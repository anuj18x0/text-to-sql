import React from 'react'

export default function SkeletonLoader() {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      gap: '12px',
      width: '100%',
      minWidth: '400px',
    }}>
      {/* Title-like skeleton */}
      <div className="shimmer" style={{
        height: '24px',
        width: '30%',
        borderRadius: '4px',
        opacity: 0.6,
      }} />
      
      {/* Large content block (simulated SQL container) */}
      <div className="shimmer" style={{
        height: '160px',
        width: '100%',
        borderRadius: '12px',
        border: '1px solid var(--border-color)',
      }} />
      
      {/* Small metadata bar */}
      <div className="shimmer" style={{
        height: '16px',
        width: '20%',
        borderRadius: '4px',
        alignSelf: 'flex-start',
        opacity: 0.4,
      }} />
    </div>
  )
}
