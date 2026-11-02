"use client";

import React from "react";
import ReactMarkdown from "react-markdown";
import { cn } from "@/lib/cn";

interface MarkdownContentProps {
  content: string;
  className?: string;
}

/**
 * Highlights @user mentions into styled executive pill badges
 */
export function highlightMentions(children: React.ReactNode): React.ReactNode {
  return React.Children.map(children, (child, index) => {
    if (typeof child === "string") {
      const parts = child.split(/(@[a-zA-Z0-9_\-\.]+)/g);
      if (parts.length === 1) return child;
      return parts.map((part, i) => {
        if (part.startsWith("@") && part.length > 1) {
          return (
            <span
              key={`${index}-${i}`}
              className="inline-flex items-center gap-0.5 px-1.5 py-0.5 mx-0.5 rounded-md font-semibold text-xs tracking-tight bg-indigo-50 text-indigo-700 border border-indigo-200/90 dark:bg-[#253745] dark:text-[#CCD0CF] dark:border-[#4A5C6A] shadow-xs"
            >
              <span className="opacity-70">@</span>
              <span>{part.slice(1)}</span>
            </span>
          );
        }
        return part;
      });
    }

    if (React.isValidElement(child) && child.props && "children" in child.props) {
      const childElement = child as React.ReactElement<{ children?: React.ReactNode }>;
      return React.cloneElement(childElement, {
        children: highlightMentions(childElement.props.children),
      });
    }

    return child;
  });
}

export function MarkdownContent({ content, className }: MarkdownContentProps) {
  if (!content) return null;

  return (
    <div
      className={cn(
        "markdown-body text-sm leading-relaxed text-zinc-700 dark:text-[#CCD0CF]",
        className
      )}
    >
      <ReactMarkdown
        components={{
          h1: ({ children, ...props }) => (
            <h1
              className="mt-4 mb-2 text-lg font-bold tracking-tight text-zinc-950 dark:text-[#F1F5F9] first:mt-0"
              {...props}
            >
              {highlightMentions(children)}
            </h1>
          ),
          h2: ({ children, ...props }) => (
            <h2
              className="mt-3.5 mb-1.5 text-base font-bold tracking-tight text-zinc-950 dark:text-[#F1F5F9] first:mt-0"
              {...props}
            >
              {highlightMentions(children)}
            </h2>
          ),
          h3: ({ children, ...props }) => (
            <h3
              className="mt-3 mb-1 text-sm font-bold tracking-tight text-zinc-950 dark:text-[#F1F5F9] first:mt-0"
              {...props}
            >
              {highlightMentions(children)}
            </h3>
          ),
          p: ({ children, ...props }) => (
            <p className="mb-2 leading-relaxed text-zinc-700 dark:text-[#CCD0CF] last:mb-0" {...props}>
              {highlightMentions(children)}
            </p>
          ),
          strong: ({ children, ...props }) => (
            <strong
              className="font-bold text-zinc-950 dark:text-[#F1F5F9]"
              {...props}
            >
              {highlightMentions(children)}
            </strong>
          ),
          em: ({ children, ...props }) => (
            <em className="italic text-zinc-800 dark:text-[#CCD0CF]" {...props}>
              {highlightMentions(children)}
            </em>
          ),
          ul: ({ children, ...props }) => (
            <ul
              className="my-2.5 space-y-1.5 pl-5 list-disc marker:text-indigo-500 dark:marker:text-[#9BA8AB]"
              {...props}
            >
              {children}
            </ul>
          ),
          ol: ({ children, ...props }) => (
            <ol
              className="my-2.5 space-y-1.5 pl-5 list-decimal marker:text-zinc-400 dark:marker:text-[#9BA8AB]"
              {...props}
            >
              {children}
            </ol>
          ),
          li: ({ children, ...props }) => (
            <li className="text-zinc-700 dark:text-[#CCD0CF] leading-relaxed" {...props}>
              {highlightMentions(children)}
            </li>
          ),
          code: ({ children, className: codeClassName, ...props }) => {
            const isInline = !codeClassName || !codeClassName.includes("language-");
            if (isInline) {
              return (
                <code
                  className="rounded-md border border-zinc-200 bg-zinc-100 px-1.5 py-0.5 font-mono text-xs font-semibold text-zinc-800 dark:border-[#253745] dark:bg-[#162736] dark:text-[#F1F5F9]"
                  {...props}
                >
                  {children}
                </code>
              );
            }
            return (
              <pre className="my-2.5 overflow-x-auto rounded-xl border border-zinc-200 bg-zinc-900 p-3 text-xs text-zinc-100 dark:border-[#253745] dark:bg-[#06141B]">
                <code className="font-mono" {...props}>
                  {children}
                </code>
              </pre>
            );
          },
          blockquote: ({ children, ...props }) => (
            <blockquote
              className="my-2 border-l-2 border-indigo-500 pl-3.5 italic text-zinc-600 dark:border-[#4A5C6A] dark:text-[#9BA8AB]"
              {...props}
            >
              {highlightMentions(children)}
            </blockquote>
          ),
          hr: () => (
            <hr className="my-3 border-zinc-200 dark:border-[#253745]" />
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
