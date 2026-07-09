"use client"

import { Toaster as Sonner, ToasterProps } from "sonner"

/**
 * Read the current theme from the .dark class on <html>.
 *
 * LocalMind uses Tailwind's class-based dark mode strategy
 * (@custom-variant dark (&:is(.dark *)) in globals.css). This hook
 * avoids the next-themes dependency by reading the class directly.
 * Returns "system" during SSR / before mount.
 */
function useTheme(): "light" | "dark" | "system" {
  if (typeof document === "undefined") return "system"
  return document.documentElement.classList.contains("dark") ? "dark" : "light"
}

const Toaster = ({ ...props }: ToasterProps) => {
  const theme = useTheme()

  return (
    <Sonner
      theme={theme}
      className="toaster group"
      style={
        {
          "--normal-bg": "var(--popover)",
          "--normal-text": "var(--popover-foreground)",
          "--normal-border": "var(--border)",
        } as React.CSSProperties
      }
      {...props}
    />
  )
}

export { Toaster }
