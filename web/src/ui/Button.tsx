import type { ButtonHTMLAttributes } from "react";
import Spinner from "./Spinner";
import { useTheme } from "./theme";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  /** Shows a spinner and disables the button. */
  loading?: boolean;
}

const SIZES: Record<Size, string> = {
  sm: "px-3 py-1 text-xs rounded-md",
  md: "px-4 py-2 text-sm rounded-lg",
};

const VARIANTS: Record<Exclude<Variant, "primary">, string> = {
  secondary: "bg-gray-700 hover:bg-gray-600 text-white",
  ghost: "border border-gray-700 text-gray-300 hover:bg-gray-800 hover:text-gray-100",
  danger: "bg-red-600 hover:bg-red-500 text-white",
};

/** Primary takes the active mode's accent; every button shares one shape and disabled style. */
export default function Button({
  variant = "primary",
  size = "md",
  loading = false,
  disabled,
  className = "",
  children,
  type = "button",
  ...rest
}: Props) {
  const theme = useTheme();
  const colour = variant === "primary" ? `${theme.accentButton} text-white` : VARIANTS[variant];
  return (
    <button
      type={type}
      disabled={disabled || loading}
      className={`inline-flex items-center justify-center gap-1.5 font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${SIZES[size]} ${colour} ${className}`}
      {...rest}
    >
      {loading && <Spinner className="w-3 h-3" />}
      {children}
    </button>
  );
}
