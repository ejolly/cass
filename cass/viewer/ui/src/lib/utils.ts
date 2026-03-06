import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
/** Merge Tailwind classes (shadcn-svelte convention). */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Add an optional `ref` property for element binding. */
export type WithElementRef<T, E extends HTMLElement = HTMLElement> = T & {
  ref?: E | null;
};

/** Remove `children` and `child` snippet props from a type. */
export type WithoutChildrenOrChild<T> = Omit<T, "children" | "child">;
