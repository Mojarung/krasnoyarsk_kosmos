import type { VariantProps } from "class-variance-authority"
import { cva } from "class-variance-authority"

export { default as Button } from "./Button.vue"

export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full text-sm font-medium select-none transition-[border-radius,background-color,color,transform,box-shadow] duration-300 ease-spring active:rounded-[14px] active:scale-[0.97] disabled:pointer-events-none disabled:opacity-40 [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4 shrink-0 [&_svg]:shrink-0 outline-none focus-visible:ring-ring/60 focus-visible:ring-3",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:shadow-[0_6px_20px_-8px_var(--primary)] hover:brightness-105",
        tonal: "bg-primary-container text-on-primary-container hover:brightness-110",
        secondary: "bg-secondary text-secondary-foreground hover:brightness-110",
        outline: "border border-input bg-transparent hover:bg-accent",
        ghost: "hover:bg-accent text-foreground",
        destructive: "bg-destructive/15 text-destructive hover:bg-destructive/25",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        "default": "h-10 px-5",
        "xs": "h-7 gap-1 px-2.5 text-xs [&_svg:not([class*='size-'])]:size-3",
        "sm": "h-8 gap-1.5 px-3.5 text-[13px]",
        "lg": "h-12 px-7 text-[15px]",
        "icon": "size-10",
        "icon-xs": "size-7 [&_svg:not([class*='size-'])]:size-3.5",
        "icon-sm": "size-8",
        "icon-lg": "size-12",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
)
export type ButtonVariants = VariantProps<typeof buttonVariants>
