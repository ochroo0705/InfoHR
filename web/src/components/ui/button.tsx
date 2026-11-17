import { cva, type VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "../../lib/utils";

// Our tokens are the only palette, see styles/tokens.css.
export const buttonVariants = cva("inline-flex items-center justify-center transition-colors disabled:opacity-50", {
  variants: {
    variant: {
      primary: "bg-violet-600 hover:bg-violet-700 text-white rounded-lg py-2",
    },
  },
  defaultVariants: {
    variant: "primary",
  },
});

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof buttonVariants>;

export function Button({ className, variant, type = "button", ...props }: ButtonProps) {
  return <button type={type} className={cn(buttonVariants({ variant }), className)} {...props} />;
}
