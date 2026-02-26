"use client";

import React from "react";

interface TimelineEvent {
  id: string;
  event_type: string;
  description: string;
  actor: string | null;
  metadata: Record<string, any>;
  timestamp: string;
}

interface IncidentTimelineProps {
  events: TimelineEvent[];
  durationMinutes?: number | null;
}

// Event type to icon/color mapping
const EVENT_CONFIG: Record<string, { icon: string; color: string; bgColor: string }> = {
  detected: { icon: "🔴", color: "text-red-600", bgColor: "bg-red-50" },
  analyzing_started: { icon: "🤖", color: "text-blue-600", bgColor: "bg-blue-50" },
  hypotheses_generated: { icon: "💡", color: "text-yellow-600", bgColor: "bg-yellow-50" },
  engineer_assigned: { icon: "👤", color: "text-purple-600", bgColor: "bg-purple-50" },
  engineer_notified: { icon: "📧", color: "text-indigo-600", bgColor: "bg-indigo-50" },
  pending_approval: { icon: "⏳", color: "text-orange-600", bgColor: "bg-orange-50" },
  action_approved: { icon: "✅", color: "text-green-600", bgColor: "bg-green-50" },
  action_rejected: { icon: "❌", color: "text-red-600", bgColor: "bg-red-50" },
  action_started: { icon: "🔄", color: "text-blue-600", bgColor: "bg-blue-50" },
  action_completed: { icon: "✅", color: "text-green-600", bgColor: "bg-green-50" },
  action_failed: { icon: "💥", color: "text-red-600", bgColor: "bg-red-50" },
  verification_passed: { icon: "✔️", color: "text-green-600", bgColor: "bg-green-50" },
  verification_failed: { icon: "⚠️", color: "text-orange-600", bgColor: "bg-orange-50" },
  incident_resolved: { icon: "🎉", color: "text-green-600", bgColor: "bg-green-50" },
  incident_escalated: { icon: "🚨", color: "text-red-600", bgColor: "bg-red-50" },
  comment_added: { icon: "💬", color: "text-gray-600", bgColor: "bg-gray-50" },
  status_changed: { icon: "🔄", color: "text-blue-600", bgColor: "bg-blue-50" },
};

const DEFAULT_CONFIG = { icon: "📌", color: "text-gray-600", bgColor: "bg-gray-50" };

function formatTimestamp(timestamp: string): string {
  const date = new Date(timestamp);
  return date.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function formatEventType(eventType: string): string {
  return eventType
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export default function IncidentTimeline({ events, durationMinutes }: IncidentTimelineProps) {
  if (!events || events.length === 0) {
    return (
      <div className="text-center py-8 text-gray-500">
        <p>No timeline events yet</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h3 className="text-lg font-semibold">Incident Timeline</h3>
        {durationMinutes !== null && durationMinutes !== undefined && (
          <div className="text-sm text-gray-600">
            Total Duration: <span className="font-semibold">{durationMinutes}m</span>
          </div>
        )}
      </div>

      {/* Timeline */}
      <div className="relative">
        {/* Vertical line */}
        <div className="absolute left-8 top-0 bottom-0 w-0.5 bg-gray-200" />

        {/* Events */}
        <div className="space-y-6">
          {events.map((event, index) => {
            const config = EVENT_CONFIG[event.event_type] || DEFAULT_CONFIG;

            return (
              <div key={event.id} className="relative flex gap-4">
                {/* Icon circle */}
                <div
                  className={`
                    relative z-10 flex-shrink-0 w-16 h-16 rounded-full
                    flex items-center justify-center text-2xl
                    border-4 border-white shadow-sm
                    ${config.bgColor}
                  `}
                >
                  {config.icon}
                </div>

                {/* Content */}
                <div className="flex-1 pb-8">
                  {/* Timestamp */}
                  <div className="text-xs text-gray-500 font-mono mb-1">
                    {formatTimestamp(event.timestamp)}
                  </div>

                  {/* Event type */}
                  <div className={`font-semibold mb-1 ${config.color}`}>
                    {formatEventType(event.event_type)}
                  </div>

                  {/* Description */}
                  <div className="text-gray-700">{event.description}</div>

                  {/* Actor */}
                  {event.actor && event.actor !== "system" && (
                    <div className="text-xs text-gray-500 mt-1">
                      by <span className="font-medium">{event.actor}</span>
                    </div>
                  )}

                  {/* Metadata (expandable details) */}
                  {Object.keys(event.metadata).length > 0 && (
                    <details className="mt-2">
                      <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-700">
                        Show details
                      </summary>
                      <pre className="mt-2 p-2 bg-gray-50 rounded text-xs overflow-auto">
                        {JSON.stringify(event.metadata, null, 2)}
                      </pre>
                    </details>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Summary */}
      <div className="mt-8 p-4 bg-gray-50 rounded-lg">
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <span className="text-gray-600">Total Events:</span>{" "}
            <span className="font-semibold">{events.length}</span>
          </div>
          <div>
            <span className="text-gray-600">Duration:</span>{" "}
            <span className="font-semibold">
              {durationMinutes !== null && durationMinutes !== undefined
                ? `${durationMinutes} minutes`
                : "Ongoing"}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
