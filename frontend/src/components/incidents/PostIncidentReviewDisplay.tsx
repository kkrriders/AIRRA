"use client";

import React from "react";
import { Button } from "@/components/ui/button";

interface ActionItem {
  description: string;
  owner: string;
  due_date?: string;
  priority: string;
  status: string;
}

interface PostmortemData {
  id: string;
  incident_id: string;
  actual_root_cause: string;
  contributing_factors: string[];
  detection_delay_reason?: string;
  duration_minutes: number;
  users_affected?: number;
  revenue_impact_usd?: number;
  what_went_well: string[];
  what_went_wrong: string[];
  lessons_learned: string[];
  action_items: ActionItem[];
  prevention_measures: string[];
  detection_improvements: string[];
  response_improvements: string[];
  ai_hypothesis_correct?: boolean;
  ai_evaluation_notes?: string;
  additional_notes?: string;
  published: boolean;
  published_at?: string;
  created_at: string;
  updated_at: string;
}

interface PostIncidentReviewDisplayProps {
  postmortem: PostmortemData;
  onEdit?: () => void;
}

export default function PostIncidentReviewDisplay({
  postmortem,
  onEdit,
}: PostIncidentReviewDisplayProps) {
  const actionItemsCompleted = postmortem.action_items.filter(
    (item) => item.status === "completed"
  ).length;
  const actionItemsTotal = postmortem.action_items.length;
  const completionPercentage =
    actionItemsTotal > 0 ? Math.round((actionItemsCompleted / actionItemsTotal) * 100) : 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold mb-2">Post-Incident Review</h2>
          {postmortem.published && postmortem.published_at && (
            <p className="text-sm text-gray-600">
              Published on {new Date(postmortem.published_at).toLocaleDateString()}
            </p>
          )}
        </div>
        {onEdit && (
          <Button onClick={onEdit} variant="outline">
            Edit PIR
          </Button>
        )}
      </div>

      {/* Impact Summary */}
      <div className="grid grid-cols-3 gap-4 p-4 bg-gray-50 rounded-lg">
        <div>
          <div className="text-sm text-gray-600">Duration</div>
          <div className="text-2xl font-bold">{postmortem.duration_minutes}m</div>
        </div>
        {postmortem.users_affected !== null && postmortem.users_affected !== undefined && (
          <div>
            <div className="text-sm text-gray-600">Users Affected</div>
            <div className="text-2xl font-bold">{postmortem.users_affected.toLocaleString()}</div>
          </div>
        )}
        {postmortem.revenue_impact_usd !== null && postmortem.revenue_impact_usd !== undefined && (
          <div>
            <div className="text-sm text-gray-600">Revenue Impact</div>
            <div className="text-2xl font-bold text-red-600">
              ${postmortem.revenue_impact_usd.toLocaleString()}
            </div>
          </div>
        )}
      </div>

      {/* Root Cause */}
      <section className="border-l-4 border-red-500 pl-4">
        <h3 className="font-semibold text-lg mb-2">Root Cause</h3>
        <p className="text-gray-700">{postmortem.actual_root_cause}</p>

        {postmortem.contributing_factors.length > 0 && (
          <div className="mt-4">
            <h4 className="font-medium mb-2">Contributing Factors:</h4>
            <ul className="list-disc list-inside space-y-1">
              {postmortem.contributing_factors.map((factor, index) => (
                <li key={index} className="text-gray-700">
                  {factor}
                </li>
              ))}
            </ul>
          </div>
        )}

        {postmortem.detection_delay_reason && (
          <div className="mt-4 p-3 bg-yellow-50 rounded">
            <h4 className="font-medium mb-1 text-yellow-800">Why Was Detection Delayed?</h4>
            <p className="text-yellow-700">{postmortem.detection_delay_reason}</p>
          </div>
        )}
      </section>

      {/* Learnings */}
      <section>
        <h3 className="font-semibold text-lg mb-4">Learnings</h3>

        <div className="grid grid-cols-2 gap-6">
          {/* What Went Well */}
          {postmortem.what_went_well.length > 0 && (
            <div className="p-4 bg-green-50 rounded-lg">
              <h4 className="font-medium mb-3 text-green-800">✅ What Went Well</h4>
              <ul className="space-y-2">
                {postmortem.what_went_well.map((item, index) => (
                  <li key={index} className="text-green-700 flex gap-2">
                    <span>•</span>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* What Went Wrong */}
          {postmortem.what_went_wrong.length > 0 && (
            <div className="p-4 bg-orange-50 rounded-lg">
              <h4 className="font-medium mb-3 text-orange-800">⚠️ What Went Wrong</h4>
              <ul className="space-y-2">
                {postmortem.what_went_wrong.map((item, index) => (
                  <li key={index} className="text-orange-700 flex gap-2">
                    <span>•</span>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* Lessons Learned */}
        {postmortem.lessons_learned.length > 0 && (
          <div className="mt-4 p-4 bg-blue-50 rounded-lg">
            <h4 className="font-medium mb-3 text-blue-800">📚 Lessons Learned</h4>
            <ul className="space-y-2">
              {postmortem.lessons_learned.map((item, index) => (
                <li key={index} className="text-blue-700 flex gap-2">
                  <span>•</span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {/* Action Items */}
      {postmortem.action_items.length > 0 && (
        <section>
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold text-lg">Action Items</h3>
            <div className="text-sm text-gray-600">
              {actionItemsCompleted} of {actionItemsTotal} completed ({completionPercentage}%)
            </div>
          </div>

          <div className="space-y-3">
            {postmortem.action_items.map((item, index) => {
              const isCompleted = item.status === "completed";
              const priorityColors = {
                low: "bg-gray-100 text-gray-700",
                medium: "bg-blue-100 text-blue-700",
                high: "bg-orange-100 text-orange-700",
                critical: "bg-red-100 text-red-700",
              };

              return (
                <div
                  key={index}
                  className={`p-4 border rounded-lg ${
                    isCompleted ? "bg-green-50 border-green-200" : "bg-white"
                  }`}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-2">
                        <span className={`px-2 py-1 rounded text-xs font-medium ${priorityColors[item.priority as keyof typeof priorityColors]}`}>
                          {item.priority.toUpperCase()}
                        </span>
                        <span className={`px-2 py-1 rounded text-xs ${
                          isCompleted ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-700"
                        }`}>
                          {item.status.replace("_", " ").toUpperCase()}
                        </span>
                      </div>

                      <p className={`font-medium ${isCompleted ? "line-through text-gray-600" : ""}`}>
                        {item.description}
                      </p>

                      <div className="flex gap-4 mt-2 text-sm text-gray-600">
                        <span>👤 {item.owner}</span>
                        {item.due_date && <span>📅 Due: {item.due_date}</span>}
                      </div>
                    </div>

                    {isCompleted && (
                      <div className="text-green-600 text-2xl">✓</div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* Improvements */}
      <section>
        <h3 className="font-semibold text-lg mb-4">How to Improve</h3>

        <div className="space-y-4">
          {postmortem.prevention_measures.length > 0 && (
            <div>
              <h4 className="font-medium mb-2">🛡️ Prevention Measures</h4>
              <ul className="list-disc list-inside space-y-1">
                {postmortem.prevention_measures.map((item, index) => (
                  <li key={index} className="text-gray-700">
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {postmortem.detection_improvements.length > 0 && (
            <div>
              <h4 className="font-medium mb-2">🔍 Detection Improvements</h4>
              <ul className="list-disc list-inside space-y-1">
                {postmortem.detection_improvements.map((item, index) => (
                  <li key={index} className="text-gray-700">
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {postmortem.response_improvements.length > 0 && (
            <div>
              <h4 className="font-medium mb-2">⚡ Response Improvements</h4>
              <ul className="list-disc list-inside space-y-1">
                {postmortem.response_improvements.map((item, index) => (
                  <li key={index} className="text-gray-700">
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </section>

      {/* AI Evaluation */}
      {(postmortem.ai_hypothesis_correct !== null || postmortem.ai_evaluation_notes) && (
        <section className="p-4 bg-purple-50 rounded-lg">
          <h3 className="font-semibold text-lg mb-3">🤖 AI Hypothesis Evaluation</h3>

          {postmortem.ai_hypothesis_correct !== null && (
            <div className="mb-2">
              <span className="font-medium">AI was correct: </span>
              <span
                className={
                  postmortem.ai_hypothesis_correct ? "text-green-600" : "text-red-600"
                }
              >
                {postmortem.ai_hypothesis_correct ? "Yes ✓" : "No ✗"}
              </span>
            </div>
          )}

          {postmortem.ai_evaluation_notes && (
            <p className="text-gray-700 italic">{postmortem.ai_evaluation_notes}</p>
          )}
        </section>
      )}

      {/* Additional Notes */}
      {postmortem.additional_notes && (
        <section>
          <h3 className="font-semibold text-lg mb-2">Additional Notes</h3>
          <p className="text-gray-700 whitespace-pre-wrap">{postmortem.additional_notes}</p>
        </section>
      )}

      {/* Footer */}
      <div className="text-sm text-gray-500 pt-4 border-t">
        <p>Created: {new Date(postmortem.created_at).toLocaleString()}</p>
        <p>Last updated: {new Date(postmortem.updated_at).toLocaleString()}</p>
      </div>
    </div>
  );
}
