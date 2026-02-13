'use client';

/**
 * Admin Panel - Engineer Incident Review
 *
 * Token-based access from email notifications. Engineers can:
 * - View incident details and AI-generated hypotheses
 * - Approve or reject AI recommendations
 * - Take manual actions or escalate
 * - Provide feedback for learning
 *
 * Security Note: React auto-escapes all rendered content to prevent XSS
 */
import { useEffect, useState, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  acknowledgeNotification,
  getIncident,
  getIncidentActions,
  approveAction,
  rejectAction,
  escalateIncident,
  addIncidentFeedback,
  type Incident,
  type Action,
} from '@/lib/api-client';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { toast } from 'sonner';
import { formatDistanceToNow } from 'date-fns';
import {
  AlertCircle,
  CheckCircle,
  Clock,
  XCircle,
  ArrowUpCircle,
  MessageSquare,
  Activity,
  Server,
} from 'lucide-react';

export default function AdminPanelPage() {
  const params = useParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const token = params.token as string;

  const [acknowledged, setAcknowledged] = useState(false);
  const [incidentId, setIncidentId] = useState<string | null>(null);

  // Dialog states
  const [rejectDialogOpen, setRejectDialogOpen] = useState(false);
  const [escalateDialogOpen, setEscalateDialogOpen] = useState(false);
  const [feedbackDialogOpen, setFeedbackDialogOpen] = useState(false);
  const [selectedActionId, setSelectedActionId] = useState<string | null>(null);
  const [rejectionReason, setRejectionReason] = useState('');
  const [escalationReason, setEscalationReason] = useState('');
  const [feedbackText, setFeedbackText] = useState('');

  // Acknowledge notification on page load
  const acknowledgeMutation = useMutation({
    mutationFn: acknowledgeNotification,
    onSuccess: (data) => {
      setAcknowledged(true);
      setIncidentId(data.incident_id || null);

      const slaStatus = data.sla_met ? 'within SLA ✅' : 'SLA missed ⚠️';
      const responseTime = data.response_time_seconds
        ? `${Math.round(data.response_time_seconds / 60)} minutes`
        : 'N/A';

      toast.success(`Notification acknowledged (${responseTime}, ${slaStatus})`);
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || 'Invalid or expired token');
    },
  });

  // Flag to ensure acknowledgement only runs once
  const [hasAttemptedAck, setHasAttemptedAck] = useState(false);

  // Auto-acknowledge on mount (flag-based to prevent infinite loops)
  useEffect(() => {
    if (token && !acknowledged && !hasAttemptedAck) {
      setHasAttemptedAck(true);
      acknowledgeMutation.mutate(token);
    }
  }, [token, acknowledged, hasAttemptedAck]); // Safe: no mutation object in dependencies

  // Fetch incident data (no auto-refresh - admin panel is one-time review)
  const { data: incident, isLoading: incidentLoading } = useQuery({
    queryKey: ['incident', incidentId],
    queryFn: () => getIncident(incidentId!),
    enabled: !!incidentId,
    refetchInterval: false, // No polling
    refetchIntervalInBackground: false, // Prevent memory leaks
  });

  // Fetch actions (no auto-refresh)
  const { data: actions = [], isLoading: actionsLoading } = useQuery({
    queryKey: ['actions', incidentId],
    queryFn: () => getIncidentActions(incidentId!),
    enabled: !!incidentId,
    refetchInterval: false, // No polling
    refetchIntervalInBackground: false, // Prevent memory leaks
  });

  // Approve action mutation
  const approveActionMutation = useMutation({
    mutationFn: ({ actionId }: { actionId: string }) =>
      approveAction(actionId, { approved_by: 'engineer', execution_mode: 'live' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['actions', incidentId] });
      toast.success('Action approved and will be executed');
    },
    onError: () => toast.error('Failed to approve action'),
  });

  // Reject action mutation
  const rejectActionMutation = useMutation({
    mutationFn: ({ actionId, reason }: { actionId: string; reason: string }) =>
      rejectAction(actionId, { rejected_by: 'engineer', rejection_reason: reason }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['actions', incidentId] });
      setRejectDialogOpen(false);
      setRejectionReason('');
      toast.success('Action rejected');
    },
    onError: () => toast.error('Failed to reject action'),
  });

  // Escalate incident mutation
  const escalateMutation = useMutation({
    mutationFn: ({ reason }: { reason: string }) =>
      escalateIncident(incidentId!, { reason, priority: 'critical' }),
    onSuccess: () => {
      toast.success('Incident escalated to higher priority');
      setEscalateDialogOpen(false);
      router.push('/');
    },
    onError: () => toast.error('Failed to escalate incident'),
  });

  // Feedback mutation
  const feedbackMutation = useMutation({
    mutationFn: ({ text }: { text: string }) =>
      addIncidentFeedback(incidentId!, {
        feedback_text: text,
        feedback_type: 'suggestion',
      }),
    onSuccess: () => {
      toast.success('Feedback submitted');
      setFeedbackDialogOpen(false);
      setFeedbackText('');
    },
    onError: () => toast.error('Failed to submit feedback'),
  });

  // Loading state
  if (acknowledgeMutation.isPending) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <Clock className="h-12 w-12 animate-spin mx-auto mb-4 text-blue-600" />
          <p className="text-lg font-medium">Validating token...</p>
        </div>
      </div>
    );
  }

  // Error state
  if (acknowledgeMutation.isError) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Card className="max-w-md">
          <CardHeader>
            <XCircle className="h-12 w-12 text-red-600 mx-auto mb-2" />
            <CardTitle className="text-center">Invalid or Expired Token</CardTitle>
            <CardDescription className="text-center">
              This notification link is no longer valid. Please request a new notification.
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    );
  }

  // Data loading
  if (incidentLoading || actionsLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <Activity className="h-12 w-12 animate-pulse mx-auto mb-4 text-blue-600" />
          <p className="text-lg font-medium">Loading incident data...</p>
        </div>
      </div>
    );
  }

  if (!incident) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Card className="max-w-md">
          <CardHeader>
            <AlertCircle className="h-12 w-12 text-yellow-600 mx-auto mb-2" />
            <CardTitle className="text-center">Incident Not Found</CardTitle>
          </CardHeader>
        </Card>
      </div>
    );
  }

  const severityColors = {
    critical: 'bg-red-600',
    high: 'bg-orange-600',
    medium: 'bg-yellow-600',
    low: 'bg-blue-600',
  };

  const statusColors = {
    open: 'bg-red-100 text-red-800',
    investigating: 'bg-yellow-100 text-yellow-800',
    mitigating: 'bg-blue-100 text-blue-800',
    resolved: 'bg-green-100 text-green-800',
    closed: 'bg-gray-100 text-gray-800',
  };

  return (
    <div className="min-h-screen bg-gray-50 py-8 px-4">
      <div className="max-w-6xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-gray-900">Incident Review</h1>
            <p className="text-gray-600 mt-1">
              Acknowledged{' '}
              {acknowledgeMutation.data?.acknowledged_at
                ? formatDistanceToNow(new Date(acknowledgeMutation.data.acknowledged_at), {
                    addSuffix: true,
                  })
                : 'just now'}
            </p>
          </div>
          <Button
            variant="outline"
            onClick={() => router.push('/')}
            className="flex items-center gap-2"
          >
            <Server className="h-4 w-4" />
            Back to Dashboard
          </Button>
        </div>

        {/* Incident Overview */}
        <Card>
          <CardHeader className={`${severityColors[incident.severity]} text-white`}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <AlertCircle className="h-8 w-8" />
                <div>
                  <CardTitle className="text-2xl">{incident.title}</CardTitle>
                  <CardDescription className="text-gray-100 mt-1">
                    {incident.affected_service}
                  </CardDescription>
                </div>
              </div>
              <div className="text-right">
                <Badge className={statusColors[incident.status]}>{incident.status}</Badge>
                <p className="text-sm text-gray-100 mt-1">
                  {formatDistanceToNow(new Date(incident.detected_at), { addSuffix: true })}
                </p>
              </div>
            </div>
          </CardHeader>
          <CardContent className="mt-6">
            <div className="space-y-4">
              <div>
                <h3 className="font-semibold text-gray-900 mb-2">Description</h3>
                <p className="text-gray-700">{incident.description}</p>
              </div>
              {incident.root_cause && (
                <div>
                  <h3 className="font-semibold text-gray-900 mb-2">Root Cause</h3>
                  <p className="text-gray-700">{incident.root_cause}</p>
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Recommended Actions */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Activity className="h-6 w-6 text-blue-600" />
              Recommended Actions
            </CardTitle>
            <CardDescription>Review and approve automated remediation actions</CardDescription>
          </CardHeader>
          <CardContent>
            {actions.length === 0 ? (
              <p className="text-gray-500 text-center py-8">No actions proposed yet</p>
            ) : (
              <div className="space-y-4">
                {actions.map((action) => (
                  <div
                    key={action.id}
                    className="border border-gray-200 rounded-lg p-4 space-y-3"
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <p className="font-medium text-gray-900">{action.action_type}</p>
                        <p className="text-sm text-gray-600 mt-1">{action.description}</p>
                      </div>
                      <div className="flex flex-col items-end gap-2">
                        {action.requires_approval && (
                          <Badge className="bg-yellow-100 text-yellow-800">Needs Approval</Badge>
                        )}
                        {action.approved && (
                          <Badge className="bg-green-100 text-green-800">Approved</Badge>
                        )}
                        {action.executed && (
                          <Badge className="bg-blue-100 text-blue-800">Executed</Badge>
                        )}
                      </div>
                    </div>

                    {action.execution_result && (
                      <div className="bg-gray-50 rounded p-3">
                        <p className="text-sm font-medium text-gray-700 mb-1">Result:</p>
                        <p className="text-sm text-gray-600">{action.execution_result}</p>
                      </div>
                    )}

                    {action.requires_approval && !action.approved && (
                      <div className="flex gap-2 mt-4">
                        <Button
                          onClick={() => approveActionMutation.mutate({ actionId: action.id })}
                          className="flex items-center gap-2"
                          disabled={approveActionMutation.isPending}
                        >
                          <CheckCircle className="h-4 w-4" />
                          Approve & Execute
                        </Button>
                        <Button
                          variant="outline"
                          onClick={() => {
                            setSelectedActionId(action.id);
                            setRejectDialogOpen(true);
                          }}
                          className="flex items-center gap-2"
                          disabled={rejectActionMutation.isPending}
                        >
                          <XCircle className="h-4 w-4" />
                          Reject
                        </Button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Quick Actions */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <MessageSquare className="h-6 w-6 text-purple-600" />
              Quick Actions
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-3">
              <Button
                variant="outline"
                onClick={() => setEscalateDialogOpen(true)}
                className="flex items-center gap-2"
                disabled={escalateMutation.isPending}
              >
                <ArrowUpCircle className="h-4 w-4" />
                Escalate to Senior Engineer
              </Button>
              <Button
                variant="outline"
                onClick={() => setFeedbackDialogOpen(true)}
                className="flex items-center gap-2"
              >
                <MessageSquare className="h-4 w-4" />
                Provide Feedback
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Reject Action Dialog */}
      <Dialog open={rejectDialogOpen} onOpenChange={setRejectDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reject Action</DialogTitle>
            <DialogDescription>
              Please provide a reason for rejecting this action.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="rejection-reason">Rejection Reason</Label>
              <Textarea
                id="rejection-reason"
                value={rejectionReason}
                onChange={(e) => setRejectionReason(e.target.value)}
                placeholder="Explain why this action should not be executed..."
                rows={4}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRejectDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                if (selectedActionId) {
                  rejectActionMutation.mutate({
                    actionId: selectedActionId,
                    reason: rejectionReason || 'No reason provided',
                  });
                }
              }}
              disabled={!rejectionReason.trim() || rejectActionMutation.isPending}
            >
              {rejectActionMutation.isPending ? 'Rejecting...' : 'Reject Action'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Escalate Incident Dialog */}
      <Dialog open={escalateDialogOpen} onOpenChange={setEscalateDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Escalate Incident</DialogTitle>
            <DialogDescription>
              This will escalate the incident to a senior engineer with critical priority.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="escalation-reason">Escalation Reason</Label>
              <Textarea
                id="escalation-reason"
                value={escalationReason}
                onChange={(e) => setEscalationReason(e.target.value)}
                placeholder="Explain why this incident needs senior engineer attention..."
                rows={4}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEscalateDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                if (escalationReason.trim()) {
                  escalateMutation.mutate({ reason: escalationReason });
                } else {
                  toast.error('Please provide an escalation reason');
                }
              }}
              disabled={!escalationReason.trim() || escalateMutation.isPending}
              className="bg-red-600 hover:bg-red-700"
            >
              {escalateMutation.isPending ? 'Escalating...' : 'Escalate'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Feedback Dialog */}
      <Dialog open={feedbackDialogOpen} onOpenChange={setFeedbackDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Provide Feedback</DialogTitle>
            <DialogDescription>
              Share your observations or suggestions about this incident.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="feedback">Feedback</Label>
              <Textarea
                id="feedback"
                value={feedbackText}
                onChange={(e) => setFeedbackText(e.target.value)}
                placeholder="Your feedback or observations..."
                rows={4}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setFeedbackDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                if (feedbackText.trim()) {
                  feedbackMutation.mutate({ text: feedbackText });
                } else {
                  toast.error('Please enter some feedback');
                }
              }}
              disabled={!feedbackText.trim() || feedbackMutation.isPending}
            >
              {feedbackMutation.isPending ? 'Submitting...' : 'Submit Feedback'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
