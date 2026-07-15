export default function SectionContainer({ children, className = '', as: Component = 'section' }) {
  return (
    <Component className={`section-container ${className}`.trim()}>
      <div className="section-inner">{children}</div>
    </Component>
  )
}
