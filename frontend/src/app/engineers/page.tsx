'use client';

/**
 * Engineers Management Page
 *
 * Lists all engineers, shows availability / workload, and allows creating new ones.
 */
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { apiClient } from '@/lib/api-client';
import { UserCheck, UserX, Plus, Loader2, AlertCircle, Mail, Slack } from 'lucide-react';

// ─── Types ──────────────────────────────────────────────────────────────────

interface Engineer {
  id: string;
  name: string;
  email: string;
  department: string | null;
  status: 'active' | 'busy' | 'on_leave' | 'offline';
  is_available: boolean;
  expertise: string[];
  current_review_count: number;
  max_concurrent_reviews: number;
  total_reviews_completed: number;
  slack_handle: string | null;
}

interface EngineerListResponse {
  items: Engineer[];
  total: number;
  pages: number;
}

interface CreateEngineerPayload {
  name: string;
  email: string;
  department: string;
  expertise: string[];
  slack_handle: string;
  max_concurrent_reviews: number;
}

// ─── API helpers ─────────────────────────────────────────────────────────────

async function fetchEngineers(): Promise<Engineer[]> {
  const response = await apiClient.get<EngineerListResponse>('/admin/engineers/', {
    params: { page_size: 100 },
  });
  return response.data.items;
}

async function createEngineer(payload: CreateEngineerPayload): Promise<Engineer> {
  const response = await apiClient.post<Engineer>('/admin/engineers/', payload);
  return response.data;
}

// ─── Status helpers ───────────────────────────────────────────────────────────

const statusConfig: Record<Engineer['status'], { label: string; className: string }> = {
  active:   { label: 'Active',    className: 'bg-green-100 text-green-800'  },
  busy:     { label: 'Busy',      className: 'bg-yellow-100 text-yellow-800' },
  on_leave: { label: 'On Leave',  className: 'bg-gray-100 text-gray-700'    },
  offline:  { label: 'Offline',   className: 'bg-red-100 text-red-800'      },
};

// ─── Add Engineer Modal ───────────────────────────────────────────────────────

function AddEngineerModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    name: '',
    email: '',
    department: '',
    expertiseRaw: '',
    slack_handle: '',
    max_concurrent_reviews: 3,
  });
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: createEngineer,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['engineers'] });
      onClose();
    },
    onError: (err: any) => {
      setError(err?.response?.data?.detail ?? 'Failed to create engineer');
    },
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    mutation.mutate({
      name: form.name,
      email: form.email,
      department: form.department,
      expertise: form.expertiseRaw.split(',').map((s) => s.trim()).filter(Boolean),
      slack_handle: form.slack_handle,
      max_concurrent_reviews: form.max_concurrent_reviews,
    });
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4">
        <h2 className="text-xl font-bold text-gray-900">Add Engineer</h2>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Name *</label>
            <input
              required
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="Alice Chen"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Email *</label>
            <input
              required
              type="email"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              placeholder="alice@example.com"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Department</label>
            <input
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={form.department}
              onChange={(e) => setForm({ ...form, department: e.target.value })}
              placeholder="Platform Engineering"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Expertise <span className="text-gray-400 font-normal">(comma-separated)</span>
            </label>
            <input
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={form.expertiseRaw}
              onChange={(e) => setForm({ ...form, expertiseRaw: e.target.value })}
              placeholder="kubernetes, aws, terraform"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Slack Handle</label>
            <input
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={form.slack_handle}
              onChange={(e) => setForm({ ...form, slack_handle: e.target.value })}
              placeholder="@alice-chen"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Max Concurrent Reviews
            </label>
            <input
              type="number"
              min={1}
              max={10}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={form.max_concurrent_reviews}
              onChange={(e) =>
                setForm({ ...form, max_concurrent_reviews: Number(e.target.value) })
              }
            />
          </div>

          {error && (
            <p className="text-sm text-red-600 flex items-center gap-1">
              <AlertCircle className="h-4 w-4" />
              {error}
            </p>
          )}

          <div className="flex gap-2 pt-2">
            <Button type="button" variant="outline" className="flex-1" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" className="flex-1" disabled={mutation.isPending}>
              {mutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
              ) : (
                <Plus className="h-4 w-4 mr-2" />
              )}
              Add Engineer
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ─── Engineer Card ────────────────────────────────────────────────────────────

function EngineerCard({ engineer }: { engineer: Engineer }) {
  const config = statusConfig[engineer.status] ?? statusConfig.offline;
  const capacityPct =
    engineer.max_concurrent_reviews > 0
      ? Math.round((engineer.current_review_count / engineer.max_concurrent_reviews) * 100)
      : 0;

  return (
    <div className="border border-gray-200 rounded-xl p-5 hover:shadow-md transition-shadow bg-white">
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <p className="font-semibold text-gray-900 text-base">{engineer.name}</p>
            {engineer.is_available ? (
              <UserCheck className="h-4 w-4 text-green-600" />
            ) : (
              <UserX className="h-4 w-4 text-gray-400" />
            )}
          </div>
          {engineer.department && (
            <p className="text-sm text-gray-500 mt-0.5">{engineer.department}</p>
          )}
        </div>
        <Badge className={config.className}>{config.label}</Badge>
      </div>

      <div className="mt-3 space-y-1 text-sm text-gray-600">
        <p className="flex items-center gap-1.5">
          <Mail className="h-3.5 w-3.5 text-gray-400" />
          {engineer.email}
        </p>
        {engineer.slack_handle && (
          <p className="flex items-center gap-1.5">
            <Slack className="h-3.5 w-3.5 text-gray-400" />
            {engineer.slack_handle}
          </p>
        )}
      </div>

      {engineer.expertise.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-3">
          {engineer.expertise.map((tag) => (
            <span
              key={tag}
              className="px-2 py-0.5 rounded-full text-xs bg-blue-50 text-blue-700 font-medium"
            >
              {tag}
            </span>
          ))}
        </div>
      )}

      <div className="mt-4">
        <div className="flex items-center justify-between text-xs text-gray-500 mb-1">
          <span>
            Workload: {engineer.current_review_count}/{engineer.max_concurrent_reviews} reviews
          </span>
          <span>{capacityPct}%</span>
        </div>
        <div className="w-full bg-gray-100 rounded-full h-1.5">
          <div
            className={`h-1.5 rounded-full transition-all ${
              capacityPct >= 90
                ? 'bg-red-500'
                : capacityPct >= 60
                ? 'bg-yellow-500'
                : 'bg-green-500'
            }`}
            style={{ width: `${capacityPct}%` }}
          />
        </div>
      </div>

      <p className="text-xs text-gray-400 mt-2">
        {engineer.total_reviews_completed} reviews completed
      </p>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function EngineersPage() {
  const [showModal, setShowModal] = useState(false);

  const { data: engineers = [], isLoading, error } = useQuery({
    queryKey: ['engineers'],
    queryFn: fetchEngineers,
    refetchInterval: 30000,
  });

  const available = engineers.filter((e) => e.is_available && e.status === 'active');
  const atCapacity = engineers.filter(
    (e) => e.current_review_count >= e.max_concurrent_reviews
  );

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Loader2 className="h-10 w-10 animate-spin text-blue-600" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Card className="max-w-sm text-center p-6">
          <AlertCircle className="h-10 w-10 text-red-500 mx-auto mb-3" />
          <p className="font-medium text-gray-800">Failed to load engineers</p>
          <p className="text-sm text-gray-500 mt-1">
            {error instanceof Error ? error.message : 'Unknown error'}
          </p>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 py-8 px-4">
      {showModal && <AddEngineerModal onClose={() => setShowModal(false)} />}

      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-gray-900">Engineers</h1>
            <p className="text-gray-500 mt-1">Team capacity and on-call readiness</p>
          </div>
          <Button onClick={() => setShowModal(true)}>
            <Plus className="h-4 w-4 mr-2" />
            Add Engineer
          </Button>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: 'Total', value: engineers.length },
            { label: 'Available', value: available.length },
            { label: 'At Capacity', value: atCapacity.length },
            {
              label: 'Reviews Active',
              value: engineers.reduce((s, e) => s + e.current_review_count, 0),
            },
          ].map(({ label, value }) => (
            <Card key={label}>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-gray-500">{label}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-3xl font-bold text-gray-900">{value}</p>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* Engineer grid */}
        {engineers.length === 0 ? (
          <Card>
            <CardContent className="py-16 text-center text-gray-400">
              <UserCheck className="h-14 w-14 mx-auto mb-4 opacity-30" />
              <p className="text-lg font-medium">No engineers yet</p>
              <p className="text-sm mt-1">Click "Add Engineer" to register the first one</p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {engineers.map((eng) => (
              <EngineerCard key={eng.id} engineer={eng} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
