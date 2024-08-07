import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

interface Props extends React.HTMLAttributes<HTMLDivElement> {
  scrollable?: boolean;
}

export function DashboardScreen({
  children,
  className,
  scrollable,
  ...props
}: Props) {
  const internals = (
    <div className={cn("px-7 py-6", className)} {...props}>
      {children}
    </div>
  );

  return scrollable ? <ScrollArea>{internals}</ScrollArea> : internals;
}
