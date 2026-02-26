"use client";

import React, { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

interface ActionItem {
  description: string;
  owner: string;
  due_date: string;
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
  action_items: ActionItem[];
  prevention_measures: string[];
  detection_improvements: string[];
  response_improvements: string[];
  ai_hypothesis_correct?: boolean;
  ai_evaluation_notes?: string;
  additional_notes?: string;
}

interface PostIncidentReviewFormProps {
  incidentId: string;
  durationMinutes?: number;
  onSubmit: (data: PostIncidentReviewData) => Promise<void>;
  onCancel: () => void;
}

export default function PostIncidentReviewForm({
  incidentId,
  durationMinutes = 0,
  onSubmit,
  onCancel,
}: PostIncidentReviewFormProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Form state
  const [rootCause, setRootCause] = useState("");
  const [contributingFactors, setContributingFactors] = useState<string[]>([""]);
  const [detectionDelay, setDetectionDelay] = useState("");
  const [usersAffected, setUsersAffected] = useState("");
  const [revenueImpact, setRevenueImpact] = useState("");

  const [whatWentWell, setWhatWentWell] = useState<string[]>([""]);
  const [whatWentWrong, setWhatWentWrong] = useState<string[]>([""]);
  const [lessonsLearned, setLessonsLearned] = useState<string[]>([""]);

  const [actionItems, setActionItems] = useState<ActionItem[]>([
    { description: "", owner: "", due_date: "", priority: "medium", status: "open" },
  ]);

  const [preventionMeasures, setPreventionMeasures] = useState<string[]>([""]);
  const [detectionImprovements, setDetectionImprovements] = useState<string[]>([""]);
  const [responseImprovements, setResponseImprovements] = useState<string[]>([""]);

  const [aiCorrect, setAiCorrect] = useState<boolean | undefined>(undefined);
  const [aiNotes, setAiNotes] = useState("");
  const [additionalNotes, setAdditionalNotes] = useState("");

  // Helper to add/remove items from arrays
  const addListItem = (setter: React.Dispatch<React.SetStateAction<string[]>>) => {
    setter((prev) => [...prev, ""]);
  };

  const removeListItem = (
    setter: React.Dispatch<React.SetStateAction<string[]>>,
    index: number
  ) => {
    setter((prev) => prev.filter((_, i) => i !== index));
  };

  const updateListItem = (
    setter: React.Dispatch<React.SetStateAction<string[]>>,
    index: number,
    value: string
  ) => {
    setter((prev) => prev.map((item, i) => (i === index ? value : item)));
  };

  const addActionItem = () => {
    setActionItems((prev) => [
      ...prev,
      { description: "", owner: "", due_date: "", priority: "medium", status: "open" },
    ]);
  };

  const removeActionItem = (index: number) => {
    setActionItems((prev) => prev.filter((_, i) => i !== index));
  };

  const updateActionItem = (index: number, field: keyof ActionItem, value: any) => {
    setActionItems((prev) =>
      prev.map((item, i) => (i === index ? { ...item, [field]: value } : item))
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    // Validation
    if (!rootCause.trim()) {
      setError("Root cause is required");
      return;
    }

    setLoading(true);

    try {
      const data: PostIncidentReviewData = {
        incident_id: incidentId,
        actual_root_cause: rootCause,
        contributing_factors: contributingFactors.filter((f) => f.trim()),
        detection_delay_reason: detectionDelay || undefined,
        duration_minutes: durationMinutes,
        users_affected: usersAffected ? parseInt(usersAffected) : undefined,
        revenue_impact_usd: revenueImpact ? parseFloat(revenueImpact) : undefined,
        what_went_well: whatWentWell.filter((w) => w.trim()),
        what_went_wrong: whatWentWrong.filter((w) => w.trim()),
        lessons_learned: lessonsLearned.filter((l) => l.trim()),
        action_items: actionItems.filter((a) => a.description.trim()),
        prevention_measures: preventionMeasures.filter((p) => p.trim()),
        detection_improvements: detectionImprovements.filter((d) => d.trim()),
        response_improvements: responseImprovements.filter((r) => r.trim()),
        ai_hypothesis_correct: aiCorrect,
        ai_evaluation_notes: aiNotes || undefined,
        additional_notes: additionalNotes || undefined,
      };

      await onSubmit(data);
    } catch (err: any) {
      setError(err.message || "Failed to create postmortem");
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-8">
      <div className="bg-blue-50 p-4 rounded-lg">
        <h2 className="text-xl font-bold mb-2">Post-Incident Review</h2>
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
            {contributingFactors.map((factor, index) => (
              <div key={index} className="flex gap-2 mt-2">
                <Input
                  value={factor}
                  onChange={(e: any) => updateListItem(setContributingFactors, index, e.target.value)}
                  placeholder="Additional factor that contributed..."
                />
                {contributingFactors.length > 1 && (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => removeListItem(setContributingFactors, index)}
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
            <Label htmlFor="usersAffected">Users Affected</Label>
            <Input
              id="usersAffected"
              type="number"
              value={usersAffected}
              onChange={(e: any) => setUsersAffected(e.target.value)}
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
              onChange={(e: any) => setRevenueImpact(e.target.value)}
              placeholder="Estimated revenue loss"
            />
          </div>
        </div>
      </section>

      {/* Learnings */}
      <section>
        <h3 className="font-semibold mb-4 text-lg">Learnings (Blameless)</h3>

        <div className="space-y-4">
          <div>
            <Label>What Went Well ✅</Label>
            <p className="text-sm text-gray-600 mb-2">Celebrate wins and reinforce good practices</p>
            {whatWentWell.map((item, index) => (
              <div key={index} className="flex gap-2 mt-2">
                <Input
                  value={item}
                  onChange={(e: any) => updateListItem(setWhatWentWell, index, e.target.value)}
                  placeholder="Something that worked well..."
                />
                {whatWentWell.length > 1 && (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => removeListItem(setWhatWentWell, index)}
                  >
                    Remove
                  </Button>
                )}
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              onClick={() => addListItem(setWhatWentWell)}
              className="mt-2"
            >
              + Add
            </Button>
          </div>

          <div>
            <Label>What Went Wrong ⚠️</Label>
            <p className="text-sm text-gray-600 mb-2">
              Focus on systems and processes, not people
            </p>
            {whatWentWrong.map((item, index) => (
              <div key={index} className="flex gap-2 mt-2">
                <Input
                  value={item}
                  onChange={(e: any) => updateListItem(setWhatWentWrong, index, e.target.value)}
                  placeholder="Something that could be improved..."
                />
                {whatWentWrong.length > 1 && (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => removeListItem(setWhatWentWrong, index)}
                  >
                    Remove
                  </Button>
                )}
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              onClick={() => addListItem(setWhatWentWrong)}
              className="mt-2"
            >
              + Add
            </Button>
          </div>

          <div>
            <Label>Lessons Learned 📚</Label>
            {lessonsLearned.map((item, index) => (
              <div key={index} className="flex gap-2 mt-2">
                <Input
                  value={item}
                  onChange={(e: any) => updateListItem(setLessonsLearned, index, e.target.value)}
                  placeholder="Key takeaway for the team..."
                />
                {lessonsLearned.length > 1 && (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => removeListItem(setLessonsLearned, index)}
                  >
                    Remove
                  </Button>
                )}
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              onClick={() => addListItem(setLessonsLearned)}
              className="mt-2"
            >
              + Add
            </Button>
          </div>
        </div>
      </section>

      {/* Action Items */}
      <section>
        <h3 className="font-semibold mb-4 text-lg">Action Items</h3>
        <p className="text-sm text-gray-600 mb-4">
          Concrete steps to prevent this from happening again
        </p>

        {actionItems.map((item, index) => (
          <div key={index} className="p-4 border rounded-lg mb-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="col-span-2">
                <Label>Description</Label>
                <Input
                  value={item.description}
                  onChange={(e: any) => updateActionItem(index, "description", e.target.value)}
                  placeholder="What needs to be done?"
                />
              </div>

              <div>
                <Label>Owner (Email)</Label>
                <Input
                  value={item.owner}
                  onChange={(e: any) => updateActionItem(index, "owner", e.target.value)}
                  placeholder="who@company.com"
                />
              </div>

              <div>
                <Label>Due Date</Label>
                <Input
                  type="date"
                  value={item.due_date}
                  onChange={(e: any) => updateActionItem(index, "due_date", e.target.value)}
                />
              </div>

              <div>
                <Label>Priority</Label>
                <select
                  value={item.priority}
                  onChange={(e) => updateActionItem(index, "priority", e.target.value)}
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
                    onClick={() => removeActionItem(index)}
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
          <div>
            <Label>Prevention Measures</Label>
            <p className="text-sm text-gray-600 mb-2">How to prevent this type of incident</p>
            {preventionMeasures.map((item, index) => (
              <div key={index} className="flex gap-2 mt-2">
                <Input
                  value={item}
                  onChange={(e: any) => updateListItem(setPreventionMeasures, index, e.target.value)}
                  placeholder="Prevention measure..."
                />
                {preventionMeasures.length > 1 && (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => removeListItem(setPreventionMeasures, index)}
                  >
                    Remove
                  </Button>
                )}
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              onClick={() => addListItem(setPreventionMeasures)}
              className="mt-2"
            >
              + Add
            </Button>
          </div>

          <div>
            <Label>Detection Improvements</Label>
            <p className="text-sm text-gray-600 mb-2">How to detect this faster</p>
            {detectionImprovements.map((item, index) => (
              <div key={index} className="flex gap-2 mt-2">
                <Input
                  value={item}
                  onChange={(e: any) => updateListItem(setDetectionImprovements, index, e.target.value)}
                  placeholder="Detection improvement..."
                />
                {detectionImprovements.length > 1 && (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => removeListItem(setDetectionImprovements, index)}
                  >
                    Remove
                  </Button>
                )}
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              onClick={() => addListItem(setDetectionImprovements)}
              className="mt-2"
            >
              + Add
            </Button>
          </div>

          <div>
            <Label>Response Improvements</Label>
            <p className="text-sm text-gray-600 mb-2">How to respond more effectively</p>
            {responseImprovements.map((item, index) => (
              <div key={index} className="flex gap-2 mt-2">
                <Input
                  value={item}
                  onChange={(e: any) => updateListItem(setResponseImprovements, index, e.target.value)}
                  placeholder="Response improvement..."
                />
                {responseImprovements.length > 1 && (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => removeListItem(setResponseImprovements, index)}
                  >
                    Remove
                  </Button>
                )}
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              onClick={() => addListItem(setResponseImprovements)}
              className="mt-2"
            >
              + Add
            </Button>
          </div>
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
                <input
                  type="radio"
                  checked={aiCorrect === true}
                  onChange={() => setAiCorrect(true)}
                />
                Yes
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="radio"
                  checked={aiCorrect === false}
                  onChange={() => setAiCorrect(false)}
                />
                No
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="radio"
                  checked={aiCorrect === undefined}
                  onChange={() => setAiCorrect(undefined)}
                />
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
          {loading ? "Saving..." : "Create Post-Incident Review"}
        </Button>
        <Button type="button" variant="outline" onClick={onCancel} disabled={loading}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
