export default function Card({
  title,
  children,
  className,
  action,
}: {
  title: string;
  children: React.ReactNode;
  className?: string;
  action?: React.ReactNode;
}): React.ReactElement {
  return (
    <div className={"rounded-lg border border-gray-800 bg-gray-900 " + (className ?? "")}>
      <div className="flex items-center justify-between border-b border-gray-800 px-4 py-3">
        <h2 className="text-sm font-medium text-gray-300">{title}</h2>
        {action}
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}
