import { Check, Home, LineChart, Settings, User } from "lucide-react";

const Register = {
  user: User,
  check: Check,
  home: Home,
  analytics: LineChart,
  settings: Settings,
} as const;

type IconComponents = typeof Register;
type IconPropsComponents = {
  [K in keyof IconComponents]: React.FC<React.HTMLAttributes<SVGElement>>;
};

export const Icons: IconPropsComponents = Register;
