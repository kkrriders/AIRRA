"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { api, getErrorMessage } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { X, AlertTriangle, Loader2, CheckCircle } from "lucide-react";
import type { IncidentSeverity } from "@/types";

interface QuickIncidentModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function QuickIncidentModal({ isOpen, onClose }: QuickIncidentModalProps) {
  const router = useRouter();
  const queryClient = useQueryClient();

  const [serviceName, setServiceName] = useState("");
  const [severity, setSeverity] = useState<IncidentSeverity>("medium");
  const [context, setContext] = useState("");

  const createMutation = useMutation({
    mutationFn: (data: { service_name: string; severity?: IncidentSeverity; context?: any }) =>
      api.createQuickIncident(data),
    onSuccess: (incident) => {
      queryClient.invalidateQueries({ queryKey: ["incidents"] });
      router.push(`/incidents/${incident.id}`);
      onClose();
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    if (!serviceName.trim()) {
      return;
    }

    const data: any = {
      service_name: serviceName.trim(),
      severity,
    };

    if (context.trim()) {
      try {
        data.context = JSON.parse(context);
      } catch {
        data.context = { notes: context };
      }
    }

    createMutation.mutate(data);
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="max-w-2xl w-full max-h-[90vh] overflow-y-auto mx-4">
        <Card className="border-border/50 bg-card">
          <CardHeader className="relative">
            <button
              onClick={onClose}
              className="absolute right-4 top-4 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:pointer-events-none"
            >
              <X className="h-4 w-4" />
              <span className="sr-only">Close</span>
            </button>
            <CardTitle className="text-2xl flex items-center gap-2">
              <AlertTriangle className="h-6 w-6 text-primary" />
              Report New Incident
            </CardTitle>
            <CardDescription>
              Quickly create and analyze an incident. Just provide the service name and we'll handle the rest.
            </CardDescription>
          </CardHeader>

          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-6">
              {/* Service Name */}
              <div className="space-y-2">
                <label htmlFor="serviceName" className="text-sm font-medium">
                  Service Name <span className="text-red-500">*</span>
                </label>
                <input
                  id="serviceName"
                  type="text"
                  value={serviceName}
                  onChange={(e) => setServiceName(e.target.value)}
                  placeholder="e.g., payment-service, order-service"
                  className="w-full bg-background border border-border/50 rounded-lg py-2 px-4 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20"
                  required
                  disabled={createMutation.isPending}
                />
                <p className="text-xs text-muted-foreground">
                  The name of the service experiencing issues
                </p>
              </div>

              {/* Severity */}
              <div className="space-y-2">
                <label className="text-sm font-medium">Severity</label>
                <div className="flex gap-2">
                  {(["low", "medium", "high", "critical"] as IncidentSeverity[]).map((sev) => (
                    <button
                      key={sev}
                      type="button"
                      onClick={() => setSeverity(sev)}
                      className={`flex-1 py-2 px-4 rounded-lg text-sm font-medium transition-all ${
                        severity === sev
                          ? sev === "critical"
                            ? "bg-red-500 text-white"
                            : sev === "high"
                            ? "bg-orange-500 text-white"
                            : sev === "medium"
                            ? "bg-yellow-500 text-white"
                            : "bg-blue-500 text-white"
                          : "bg-muted hover:bg-muted/80"
                      }`}
                      disabled={createMutation.isPending}
                    >
                      {sev}
                    </button>
                  ))}
                </div>
              </div>

              {/* Optional Context */}
              <div className="space-y-2">
                <label htmlFor="context" className="text-sm font-medium">
                  Additional Context <span className="text-muted-foreground">(optional)</span>
                </label>
                <textarea
                  id="context"
                  value={context}
                  onChange={(e) => setContext(e.target.value)}
                  placeholder='e.g., Recent deployment: v2.3.1, Affected regions: us-east-1'
                  rows={3}
                  className="w-full bg-background border border-border/50 rounded-lg py-2 px-4 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 resize-none"
                  disabled={createMutation.isPending}
                />
                <p className="text-xs text-muted-foreground">
                  Any additional information that might help with analysis
                </p>
              </div>

              {/* Info Box */}
              <div className="bg-primary/10 border border-primary/20 rounded-lg p-4">
                <div className="flex gap-2">
                  <CheckCircle className="h-5 w-5 text-primary flex-shrink-0 mt-0.5" />
                  <div className="text-sm space-y-1">
                    <p className="font-medium text-foreground">What happens next:</p>
                    <ul className="text-muted-foreground space-y-1 list-disc list-inside">
                      <li>Auto-detect anomalies from metrics</li>
                      <li>Generate hypotheses using AI</li>
                      <li>Recommend remediation actions</li>
                      <li>Get complete results in 10-30 seconds</li>
                    </ul>
                  </div>
                </div>
              </div>

              {/* Error Message */}
              {createMutation.isError && (
                <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-4">
                  <p className="text-sm text-red-500">
                    {getErrorMessage(createMutation.error)}
                  </p>
                </div>
              )}

              {/* Actions */}
              <div className="flex gap-3 pt-4">
                <Button
                  type="button"
                  variant="outline"
                  onClick={onClose}
                  disabled={createMutation.isPending}
                  className="flex-1"
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  disabled={createMutation.isPending || !serviceName.trim()}
                  className="flex-1 gap-2"
                >
                  {createMutation.isPending ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Analyzing...
                    </>
                  ) : (
                    "Create & Analyze"
                  )}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
