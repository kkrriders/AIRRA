"use client";

import React, { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

interface ActionItem {
  id: string;
  description: string;
  owner: string;
  due_date?: string;
  priority: "low" | "medium" | "high" | "critical";
  status: "open" | "in_progress" | "completed" | "cancelled";
}

interface PostIncidentReviewData {
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
  action_items: Omit<ActionItem, "id">[];
  prevention_measures: string[];
  detection_improvements: string[];
  response_improvements: string[];
  ai_hypothesis_correct?: boolean;
  ai_evaluation_notes?: string;
  additional_notes?: string;
}

interface InitialData {
  actual_root_cause?: string;
  contributing_factors?: string[];
  detection_delay_reason?: string | null;
  duration_minutes?: number;
  users_affected?: number | null;
  revenue_impact_usd?: number | null;
  what_went_well?: string[];
  what_went_wrong?: string[];
  lessons_learned?: string[];
  action_items?: Omit<ActionItem, "id">[];
  prevention_measures?: string[];
  detection_improvements?: string[];
  response_improvements?: string[];
  ai_hypothesis_correct?: boolean | null;
  ai_evaluation_notes?: string | null;
  additional_notes?: string | null;
}

interface PostIncidentReviewFormProps {
  incidentId: string;
  durationMinutes?: number;
  initialData?: InitialData;
  isEditing?: boolean;
  onSubmit: (data: PostIncidentReviewData) => Promise<void>;
  onCancel: () => void;
}

// Stable item factory — UUID generated once at creation, not on each render
function makeItem(value = ""): { id: string; value: string } {
  return { id: crypto.randomUUID(), value };
}

function makeActionItem(partial?: Partial<Omit<ActionItem, "id">>): ActionItem {
  return {
    id: crypto.randomUUID(),
    description: partial?.description ?? "",
    owner: partial?.owner ?? "",
    due_date: partial?.due_date ?? "",
    priority: partial?.priority ?? "medium",
    status: partial?.status ?? "open",
  };
}

function initItems(values?: string[]): { id: string; value: string }[] {
  if (values && values.length > 0) return values.map((v) => makeItem(v));
  return [makeItem()];
}

export default function PostIncidentReviewForm({
  incidentId,
  durationMinutes = 0,
  initialData,
  isEditing = false,
  onSubmit,
  onCancel,
}: PostIncidentReviewFormProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Form state — initialised from initialData when editing
  const [rootCause, setRootCause] = useState(initialData?.actual_root_cause ?? "");
  const [contributingFactors, setContributingFactors] = useState(
    initItems(initialData?.contributing_factors)
  );
  const [detectionDelay, setDetectionDelay] = useState(
    initialData?.detection_delay_reason ?? ""
  );
  const [duration, setDuration] = useState(
    String(initialData?.duration_minutes ?? durationMinutes)
  );
  const [usersAffected, setUsersAffected] = useState(
    initialData?.users_affected != null ? String(initialData.users_affected) : ""
  );
  const [revenueImpact, setRevenueImpact] = useState(
    initialData?.revenue_impact_usd != null ? String(initialData.revenue_impact_usd) : ""
  );

  const [whatWentWell, setWhatWentWell] = useState(initItems(initialData?.what_went_well));
  const [whatWentWrong, setWhatWentWrong] = useState(initItems(initialData?.what_went_wrong));
  const [lessonsLearned, setLessonsLearned] = useState(initItems(initialData?.lessons_learned));

  const [actionItems, setActionItems] = useState<ActionItem[]>(
    initialData?.action_items?.length
      ? initialData.action_items.map((a) => makeActionItem(a))
      : [makeActionItem()]
  );

  const [preventionMeasures, setPreventionMeasures] = useState(
    initItems(initialData?.prevention_measures)
  );
  const [detectionImprovements, setDetectionImprovements] = useState(
    initItems(initialData?.detection_improvements)
  );
  const [responseImprovements, setResponseImprovements] = useState(
    initItems(initialData?.response_improvements)
  );

  const [aiCorrect, setAiCorrect] = useState<boolean | undefined>(
    initialData?.ai_hypothesis_correct ?? undefined
  );
  const [aiNotes, setAiNotes] = useState(initialData?.ai_evaluation_notes ?? "");
  const [additionalNotes, setAdditionalNotes] = useState(
    initialData?.additional_notes ?? ""
  );

  // Helpers for {id, value}[] lists
  type ListSetter = React.Dispatch<React.SetStateAction<{ id: string; value: string }[]>>;

  const addListItem = (setter: ListSetter) => setter((prev) => [...prev, makeItem()]);

  const removeListItem = (setter: ListSetter, id: string) =>
    setter((prev) => prev.filter((item) => item.id !== id));

  const updateListItem = (setter: ListSetter, id: string, value: string) =>
    setter((prev) => prev.map((item) => (item.id === id ? { ...item, value } : item)));

  // Helpers for action items
  const addActionItem = () => setActionItems((prev) => [...prev, makeActionItem()]);

  const removeActionItem = (id: string) =>
    setActionItems((prev) => prev.filter((item) => item.id !== id));

  const updateActionItem = (id: string, field: keyof Omit<ActionItem, "id">, value: string) =>
    setActionItems((prev) =>
      prev.map((item) => (item.id === id ? { ...item, [field]: value } : item))
    );

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!rootCause.trim()) {
      setError("Root cause is required");
      return;
    }

    setLoading(true);

    try {
      const data: PostIncidentReviewData = {
        incident_id: incidentId,
        actual_root_cause: rootCause,
        contributing_factors: contributingFactors.map((i) => i.value).filter(Boolean),
        detection_delay_reason: detectionDelay || undefined,
        duration_minutes: parseInt(duration) || 0,
        users_affected: usersAffected ? parseInt(usersAffected) : undefined,
        revenue_impact_usd: revenueImpact ? parseFloat(revenueImpact) : undefined,
        what_went_well: whatWentWell.map((i) => i.value).filter(Boolean),
        what_went_wrong: whatWentWrong.map((i) => i.value).filter(Boolean),
        lessons_learned: lessonsLearned.map((i) => i.value).filter(Boolean),
        action_items: actionItems
          .filter((a) => a.description.trim())
          .map(({ id: _id, ...rest }) => rest),
        prevention_measures: preventionMeasures.map((i) => i.value).filter(Boolean),
        detection_improvements: detectionImprovements.map((i) => i.value).filter(Boolean),
        response_improvements: responseImprovements.map((i) => i.value).filter(Boolean),
        ai_hypothesis_correct: aiCorrect,
        ai_evaluation_notes: aiNotes || undefined,
        additional_notes: additionalNotes || undefined,
      };

      await onSubmit(data);
    } catch (err: any) {
      setError(err.message || "Failed to save review");
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-8">
      <div className="bg-blue-50 p-4 rounded-lg">
        <h2 className="text-xl font-bold mb-2">
          {isEditing ? "Edit Post-Incident Review" : "Post-Incident Review"}
        </h2>
        <p className="text-sm text-gray-600">
          Document what happened, why it happened, and how to prevent it in the future.
          This is a blameless review focused on systems and processes, not individuals.
        </p>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 p-4 rounded">
          {error}
        </div>
      )}

      {/* Root Cause */}
      <section>
        <h3 className="font-semibold mb-4 text-lg">Root Cause Analysis</h3>

        <div className="space-y-4">
          <div>
            <Label htmlFor="rootCause">
              Actual Root Cause <span className="text-red-500">*</span>
            </Label>
            <Textarea
              id="rootCause"
              value={rootCause}
              onChange={(e) => setRootCause(e.target.value)}
              placeholder="What actually caused this incident? Be specific..."
              rows={3}
              required
            />
          </div>

          <div>
            <Label>Contributing Factors</Label>
            {contributingFactors.map((item) => (
              <div key={item.id} className="flex gap-2 mt-2">
                <Input
                  value={item.value}
                  onChange={(e) => updateListItem(setContributingFactors, item.id, e.target.value)}
                  placeholder="Additional factor that contributed..."
                />
                {contributingFactors.length > 1 && (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => removeListItem(setContributingFactors, item.id)}
                  >
                    Remove
                  </Button>
                )}
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              onClick={() => addListItem(setContributingFactors)}
              className="mt-2"
            >
              + Add Factor
            </Button>
          </div>

          <div>
            <Label htmlFor="detectionDelay">Why Was Detection Delayed? (if applicable)</Label>
            <Textarea
              id="detectionDelay"
              value={detectionDelay}
              onChange={(e) => setDetectionDelay(e.target.value)}
              placeholder="Why didn't we catch this earlier?"
              rows={2}
            />
          </div>
        </div>
      </section>

      {/* Impact */}
      <section>
        <h3 className="font-semibold mb-4 text-lg">Impact Assessment</h3>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <Label htmlFor="duration">Duration (minutes)</Label>
            <Input
              id="duration"
              type="number"
              min="0"
              value={duration}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setDuration(e.target.value)}
              placeholder="Total incident duration"
            />
          </div>

          <div>
            <Label htmlFor="usersAffected">Users Affected</Label>
            <Input
              id="usersAffected"
              type="number"
              value={usersAffected}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setUsersAffected(e.target.value)}
              placeholder="Estimated number of users"
            />
          </div>

          <div>
            <Label htmlFor="revenueImpact">Revenue Impact (USD)</Label>
            <Input
              id="revenueImpact"
              type="number"
              step="0.01"
              value={revenueImpact}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setRevenueImpact(e.target.value)}
              placeholder="Estimated revenue loss"
            />
          </div>
        </div>
      </section>

      {/* Learnings */}
      <section>
        <h3 className="font-semibold mb-4 text-lg">Learnings (Blameless)</h3>

        <div className="space-y-4">
          {(
            [
              { label: "What Went Well ✅", state: whatWentWell, setter: setWhatWentWell, placeholder: "Something that worked well..." },
              { label: "What Went Wrong ⚠️", state: whatWentWrong, setter: setWhatWentWrong, placeholder: "Something that could be improved..." },
              { label: "Lessons Learned 📚", state: lessonsLearned, setter: setLessonsLearned, placeholder: "Key takeaway for the team..." },
            ] as const
          ).map(({ label, state, setter, placeholder }) => (
            <div key={label}>
              <Label>{label}</Label>
              {state.map((item) => (
                <div key={item.id} className="flex gap-2 mt-2">
                  <Input
                    value={item.value}
                    onChange={(e) => updateListItem(setter as ListSetter, item.id, e.target.value)}
                    placeholder={placeholder}
                  />
                  {state.length > 1 && (
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => removeListItem(setter as ListSetter, item.id)}
                    >
                      Remove
                    </Button>
                  )}
                </div>
              ))}
              <Button
                type="button"
                variant="outline"
                onClick={() => addListItem(setter as ListSetter)}
                className="mt-2"
              >
                + Add
              </Button>
            </div>
          ))}
        </div>
      </section>

      {/* Action Items */}
      <section>
        <h3 className="font-semibold mb-4 text-lg">Action Items</h3>
        <p className="text-sm text-gray-600 mb-4">
          Concrete steps to prevent this from happening again
        </p>

        {actionItems.map((item) => (
          <div key={item.id} className="p-4 border rounded-lg mb-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="col-span-2">
                <Label>Description</Label>
                <Input
                  value={item.description}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => updateActionItem(item.id, "description", e.target.value)}
                  placeholder="What needs to be done?"
                />
              </div>

              <div>
                <Label>Owner (Email)</Label>
                <Input
                  value={item.owner}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => updateActionItem(item.id, "owner", e.target.value)}
                  placeholder="who@company.com"
                />
              </div>

              <div>
                <Label>Due Date</Label>
                <Input
                  type="date"
                  value={item.due_date}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => updateActionItem(item.id, "due_date", e.target.value)}
                />
              </div>

              <div>
                <Label>Priority</Label>
                <select
                  value={item.priority}
                  onChange={(e) => updateActionItem(item.id, "priority", e.target.value)}
                  className="w-full p-2 border rounded"
                >
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                  <option value="critical">Critical</option>
                </select>
              </div>

              <div className="flex items-end">
                {actionItems.length > 1 && (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => removeActionItem(item.id)}
                    className="w-full"
                  >
                    Remove Action Item
                  </Button>
                )}
              </div>
            </div>
          </div>
        ))}

        <Button type="button" variant="outline" onClick={addActionItem}>
          + Add Action Item
        </Button>
      </section>

      {/* Improvements */}
      <section>
        <h3 className="font-semibold mb-4 text-lg">How to Improve</h3>

        <div className="space-y-4">
          {(
            [
              { label: "Prevention Measures", desc: "How to prevent this type of incident", state: preventionMeasures, setter: setPreventionMeasures, placeholder: "Prevention measure..." },
              { label: "Detection Improvements", desc: "How to detect this faster", state: detectionImprovements, setter: setDetectionImprovements, placeholder: "Detection improvement..." },
              { label: "Response Improvements", desc: "How to respond more effectively", state: responseImprovements, setter: setResponseImprovements, placeholder: "Response improvement..." },
            ] as const
          ).map(({ label, desc, state, setter, placeholder }) => (
            <div key={label}>
              <Label>{label}</Label>
              <p className="text-sm text-gray-600 mb-2">{desc}</p>
              {state.map((item) => (
                <div key={item.id} className="flex gap-2 mt-2">
                  <Input
                    value={item.value}
                    onChange={(e) => updateListItem(setter as ListSetter, item.id, e.target.value)}
                    placeholder={placeholder}
                  />
                  {state.length > 1 && (
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => removeListItem(setter as ListSetter, item.id)}
                    >
                      Remove
                    </Button>
                  )}
                </div>
              ))}
              <Button
                type="button"
                variant="outline"
                onClick={() => addListItem(setter as ListSetter)}
                className="mt-2"
              >
                + Add
              </Button>
            </div>
          ))}
        </div>
      </section>

      {/* AI Evaluation */}
      <section>
        <h3 className="font-semibold mb-4 text-lg">AI Hypothesis Evaluation</h3>

        <div className="space-y-4">
          <div>
            <Label>Was the AI hypothesis correct?</Label>
            <div className="flex gap-4 mt-2">
              <label className="flex items-center gap-2">
                <input type="radio" checked={aiCorrect === true} onChange={() => setAiCorrect(true)} />
                Yes
              </label>
              <label className="flex items-center gap-2">
                <input type="radio" checked={aiCorrect === false} onChange={() => setAiCorrect(false)} />
                No
              </label>
              <label className="flex items-center gap-2">
                <input type="radio" checked={aiCorrect === undefined} onChange={() => setAiCorrect(undefined)} />
                Not applicable
              </label>
            </div>
          </div>

          <div>
            <Label htmlFor="aiNotes">AI Evaluation Notes</Label>
            <Textarea
              id="aiNotes"
              value={aiNotes}
              onChange={(e) => setAiNotes(e.target.value)}
              placeholder="Feedback on AI performance for learning..."
              rows={2}
            />
          </div>
        </div>
      </section>

      {/* Additional Notes */}
      <section>
        <Label htmlFor="additionalNotes">Additional Notes</Label>
        <Textarea
          id="additionalNotes"
          value={additionalNotes}
          onChange={(e) => setAdditionalNotes(e.target.value)}
          placeholder="Any other relevant information..."
          rows={3}
        />
      </section>

      {/* Actions */}
      <div className="flex gap-4 pt-4 border-t">
        <Button type="submit" disabled={loading} className="flex-1">
          {loading ? "Saving..." : isEditing ? "Update Review" : "Create Post-Incident Review"}
        </Button>
        <Button type="button" variant="outline" onClick={onCancel} disabled={loading}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
