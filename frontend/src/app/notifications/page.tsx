'use client';

/**
 * Notifications Dashboard
 *
 * Shows all incident notifications, acknowledgements, and SLA metrics
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { apiClient } from '@/lib/api-client';
import { formatDistanceToNow } from 'date-fns';
import { Bell, Clock, CheckCircle, XCircle, TrendingUp, Mail, MessageSquare } from 'lucide-react';

interface Notification {
  id: string;
  engineer_id: string;
  incident_id: string | null;
  channel: 'email' | 'slack' | 'sms' | 'webhook';
  status: 'pending' | 'sent' | 'delivered' | 'failed' | 'acknowledged';
  priority: 'critical' | 'high' | 'normal' | 'low';
  subject: string;
  message: string;
  recipient_address: string;
  sent_at: string | null;
  delivered_at: string | null;
  acknowledged_at: string | null;
  response_time_seconds: number | null;
  sla_target_seconds: number;
  sla_met: boolean | null;
  escalated: boolean;
  created_at: string;
}

interface NotificationStats {
  total_sent: number;
  total_delivered: number;
  total_acknowledged: number;
  total_failed: number;
  average_response_time_seconds: number | null;
  sla_compliance_rate: number | null;
  escalation_rate: number | null;
}

async function getNotifications(page: number, pageSize: number) {
  const response = await apiClient.get('/notifications/', {
    params: { page, page_size: pageSize },
  });
  return response.data;
}

async function getNotificationStats(): Promise<NotificationStats> {
  const response = await apiClient.get('/notifications/stats/summary');
  return response.data;
}

export default function NotificationsDashboard() {
  const [page, setPage] = useState(1);
  const pageSize = 20;

  const { data: notificationsData, isLoading: notificationsLoading } = useQuery({
    queryKey: ['notifications', page],
    queryFn: () => getNotifications(page, pageSize),
    refetchInterval: 30000, // Refresh every 30 seconds
    refetchIntervalInBackground: false, // Stop refreshing when tab is hidden
    retry: 3,
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30000),
  });

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['notification-stats'],
    queryFn: getNotificationStats,
    refetchInterval: 60000, // Refresh every minute
    refetchIntervalInBackground: false,
    retry: 3,
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30000),
  });

  const notifications: Notification[] = notificationsData?.items || [];
  const totalPages = notificationsData?.pages || 1;

  const statusColors = {
    pending: 'bg-gray-100 text-gray-800',
    sent: 'bg-blue-100 text-blue-800',
    delivered: 'bg-green-100 text-green-800',
    failed: 'bg-red-100 text-red-800',
    acknowledged: 'bg-purple-100 text-purple-800',
  };

  const priorityColors = {
    critical: 'bg-red-600 text-white',
    high: 'bg-orange-600 text-white',
    normal: 'bg-blue-600 text-white',
    low: 'bg-gray-600 text-white',
  };

  const channelIcons = {
    email: Mail,
    slack: MessageSquare,
    sms: Bell,
    webhook: TrendingUp,
  };

  const formatResponseTime = (seconds: number | null) => {
    if (!seconds) return 'N/A';
    const minutes = Math.round(seconds / 60);
    if (minutes < 1) return `${seconds}s`;
    if (minutes < 60) return `${minutes}m`;
    const hours = Math.round(minutes / 60);
    return `${hours}h`;
  };

  return (
    <div className="min-h-screen bg-gray-50 py-8 px-4">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-3">
              <Bell className="h-8 w-8" />
              Notifications Dashboard
            </h1>
            <p className="text-gray-600 mt-1">Track incident notifications and SLA metrics</p>
          </div>
        </div>

        {/* Stats */}
        {!statsLoading && stats && (
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium text-gray-600">
                  Total Sent
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold">{stats.total_sent}</div>
                <p className="text-xs text-gray-500 mt-1">
                  {stats.total_delivered} delivered
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium text-gray-600">
                  Acknowledged
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold">{stats.total_acknowledged}</div>
                <p className="text-xs text-gray-500 mt-1">
                  {stats.total_sent > 0
                    ? Math.round((stats.total_acknowledged / stats.total_sent) * 100)
                    : 0}
                  % response rate
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium text-gray-600">
                  Avg Response Time
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold">
                  {formatResponseTime(stats.average_response_time_seconds)}
                </div>
                <p className="text-xs text-gray-500 mt-1">Average acknowledgement time</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium text-gray-600">
                  SLA Compliance
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold">
                  {stats.sla_compliance_rate !== null
                    ? `${Math.round(stats.sla_compliance_rate * 100)}%`
                    : 'N/A'}
                </div>
                <p className="text-xs text-gray-500 mt-1">
                  {stats.escalation_rate !== null
                    ? `${Math.round(stats.escalation_rate * 100)}% escalated`
                    : ''}
                </p>
              </CardContent>
            </Card>
          </div>
        )}

        {/* Notifications List */}
        <Card>
          <CardHeader>
            <CardTitle>Recent Notifications</CardTitle>
            <CardDescription>
              Showing page {page} of {totalPages}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {notificationsLoading ? (
              <div className="text-center py-12">
                <Clock className="h-12 w-12 animate-spin mx-auto mb-4 text-blue-600" />
                <p>Loading notifications...</p>
              </div>
            ) : notifications.length === 0 ? (
              <div className="text-center py-12 text-gray-500">
                <Bell className="h-16 w-16 mx-auto mb-4 opacity-30" />
                <p className="text-lg font-medium">No Notifications</p>
                <p className="text-sm mt-2">No notifications have been sent yet</p>
              </div>
            ) : (
              <>
                <div className="space-y-4">
                  {notifications.map((notification) => {
                    const ChannelIcon = channelIcons[notification.channel];
                    return (
                      <div
                        key={notification.id}
                        className="border border-gray-200 rounded-lg p-4 hover:bg-gray-50 transition-colors"
                      >
                        <div className="flex items-start justify-between">
                          <div className="flex-1">
                            <div className="flex items-center gap-3 mb-2">
                              <ChannelIcon className="h-5 w-5 text-gray-400" />
                              <p className="font-semibold text-gray-900">
                                {notification.subject}
                              </p>
                            </div>
                            <p className="text-sm text-gray-600 mb-2">
                              To: {notification.recipient_address}
                            </p>
                            <div className="flex items-center gap-2 flex-wrap">
                              <Badge className={statusColors[notification.status]}>
                                {notification.status}
                              </Badge>
                              <Badge className={priorityColors[notification.priority]}>
                                {notification.priority}
                              </Badge>
                              {notification.channel && (
                                <Badge variant="outline">{notification.channel}</Badge>
                              )}
                              {notification.escalated && (
                                <Badge className="bg-orange-100 text-orange-800">
                                  Escalated
                                </Badge>
                              )}
                            </div>
                          </div>

                          <div className="text-right ml-4">
                            {notification.acknowledged_at ? (
                              <div className="text-sm">
                                <div className="flex items-center gap-2 justify-end text-green-600">
                                  <CheckCircle className="h-4 w-4" />
                                  <span className="font-medium">Acknowledged</span>
                                </div>
                                <p className="text-xs text-gray-500 mt-1">
                                  {formatDistanceToNow(new Date(notification.acknowledged_at), {
                                    addSuffix: true,
                                  })}
                                </p>
                                {notification.response_time_seconds !== null && (
                                  <p className="text-xs text-gray-500">
                                    Response: {formatResponseTime(notification.response_time_seconds)}
                                  </p>
                                )}
                                {notification.sla_met !== null && (
                                  <div className="mt-1">
                                    {notification.sla_met ? (
                                      <Badge className="bg-green-100 text-green-800 text-xs">
                                        SLA Met ✓
                                      </Badge>
                                    ) : (
                                      <Badge className="bg-red-100 text-red-800 text-xs">
                                        SLA Missed
                                      </Badge>
                                    )}
                                  </div>
                                )}
                              </div>
                            ) : notification.status === 'failed' ? (
                              <div className="flex items-center gap-2 text-red-600">
                                <XCircle className="h-4 w-4" />
                                <span className="text-sm font-medium">Failed</span>
                              </div>
                            ) : (
                              <div className="text-sm text-gray-500">
                                <Clock className="h-4 w-4 inline mr-1" />
                                {notification.sent_at
                                  ? formatDistanceToNow(new Date(notification.sent_at), {
                                      addSuffix: true,
                                    })
                                  : 'Pending'}
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Pagination */}
                {totalPages > 1 && (
                  <div className="flex items-center justify-between mt-6">
                    <Button
                      variant="outline"
                      onClick={() => setPage(page - 1)}
                      disabled={page === 1}
                    >
                      Previous
                    </Button>
                    <span className="text-sm text-gray-600">
                      Page {page} of {totalPages}
                    </span>
                    <Button
                      variant="outline"
                      onClick={() => setPage(page + 1)}
                      disabled={page === totalPages}
                    >
                      Next
                    </Button>
                  </div>
                )}
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
