export default function Settings() {
  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-2xl mx-auto px-6 py-10">
        <h2 className="text-xl font-semibold text-gray-100 mb-1">Settings</h2>
        <p className="text-sm text-gray-500 mb-8">Configure your Strides AI preferences.</p>

        <div className="space-y-6">
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-3">
              General
            </h3>
            <div className="bg-gray-900 border border-gray-800 rounded-lg divide-y divide-gray-800">
              <div className="px-4 py-3 flex items-center justify-between">
                <span className="text-sm text-gray-300">Placeholder setting</span>
                <span className="text-xs text-gray-600">Coming soon</span>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
