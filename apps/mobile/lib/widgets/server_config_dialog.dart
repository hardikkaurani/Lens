import 'package:flutter/material.dart';
import '../core/config/api_config.dart';
import '../core/network/api_client.dart';
import '../core/theme/app_theme.dart';

/// Modal bottom sheet allowing developers to view, modify, and test the LENS API Base URL.
class ServerConfigDialog extends StatefulWidget {
  final ApiConfig config;
  final VoidCallback? onSaved;

  const ServerConfigDialog({
    super.key,
    required this.config,
    this.onSaved,
  });

  static Future<void> show(BuildContext context, {VoidCallback? onSaved}) {
    return showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: AppTheme.surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) => Padding(
        padding: EdgeInsets.only(
          bottom: MediaQuery.of(ctx).viewInsets.bottom,
        ),
        child: ServerConfigDialog(
          config: ApiConfig(),
          onSaved: onSaved,
        ),
      ),
    );
  }

  @override
  State<ServerConfigDialog> createState() => _ServerConfigDialogState();
}

class _ServerConfigDialogState extends State<ServerConfigDialog> {
  late final TextEditingController _controller;
  bool _testing = false;
  String? _testResult;
  bool _testSuccess = false;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: widget.config.baseUrl);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _testConnection() async {
    final url = _controller.text.trim();
    if (url.isEmpty) {
      setState(() {
        _testSuccess = false;
        _testResult = 'Please enter an API URL to test.';
      });
      return;
    }

    if (!ApiConfig.isValidUrl(url)) {
      setState(() {
        _testSuccess = false;
        _testResult = 'Invalid URL. Only http:// and https:// URLs with a valid host are accepted.';
      });
      return;
    }

    setState(() {
      _testing = true;
      _testResult = null;
    });

    try {
      final client = ApiClient();
      final res = await client.checkHealthForUrl(url);
      final status = res['status'] ?? 'unknown';
      if (mounted) {
        setState(() {
          _testing = false;
          _testSuccess = true;
          _testResult = 'Connection successful! (status: $status)';
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _testing = false;
          _testSuccess = false;
          _testResult = e.toString();
        });
      }
    }
  }

  void _applyPreset(String url) {
    setState(() {
      _controller.text = url;
      _testResult = null;
    });
  }

  Future<void> _saveAndClose() async {
    final url = _controller.text.trim();
    if (url.isEmpty) return;

    if (!ApiConfig.isValidUrl(url)) {
      setState(() {
        _testSuccess = false;
        _testResult = 'Cannot save: URL is invalid or uses an unsupported scheme.';
      });
      return;
    }

    try {
      await widget.config.setBaseUrl(url);
      if (mounted) {
        Navigator.of(context).pop();
        widget.onSaved?.call();
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _testSuccess = false;
          _testResult = 'Failed to save configuration: $e';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Row(
                  children: [
                    Icon(Icons.dns_rounded, size: 20, color: AppTheme.primaryLight),
                    SizedBox(width: 8),
                    Text(
                      'Server Configuration',
                      style: TextStyle(
                        color: AppTheme.textPrimary,
                        fontSize: 17,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ],
                ),
                IconButton(
                  onPressed: () => Navigator.of(context).pop(),
                  icon: const Icon(Icons.close_rounded, size: 20),
                  color: AppTheme.textMuted,
                  visualDensity: VisualDensity.compact,
                ),
              ],
            ),
            const SizedBox(height: 6),
            const Text(
              'Specify the local FastAPI backend address. For physical phones, use your local Wi-Fi host IP or adb reverse.',
              style: TextStyle(color: AppTheme.textSecondary, fontSize: 13),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _controller,
              style: const TextStyle(fontSize: 14, fontFamily: 'monospace'),
              decoration: const InputDecoration(
                labelText: 'API Base URL',
                hintText: 'http://<SERVER_HOST>:8000',
                prefixIcon: Icon(Icons.link_rounded, size: 18),
              ),
              keyboardType: TextInputType.url,
            ),
            const SizedBox(height: 12),
            const Text(
              'Quick Presets:',
              style: TextStyle(
                color: AppTheme.textMuted,
                fontSize: 11,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 6),
            Wrap(
              spacing: 8,
              runSpacing: 6,
              children: [
                _PresetChip(
                  label: 'Android Emulator (10.0.2.2:8000)',
                  onTap: () => _applyPreset('http://10.0.2.2:8000'),
                ),
                _PresetChip(
                  label: 'Localhost / ADB Reverse (127.0.0.1:8000)',
                  onTap: () => _applyPreset('http://127.0.0.1:8000'),
                ),
              ],
            ),
            if (_testResult != null) ...[
              const SizedBox(height: 14),
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: _testSuccess
                      ? AppTheme.statusCompleted.withValues(alpha: 0.1)
                      : AppTheme.statusFailed.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(
                    color: _testSuccess
                        ? AppTheme.statusCompleted.withValues(alpha: 0.3)
                        : AppTheme.statusFailed.withValues(alpha: 0.3),
                  ),
                ),
                child: Row(
                  children: [
                    Icon(
                      _testSuccess ? Icons.check_circle_outline : Icons.error_outline,
                      size: 18,
                      color: _testSuccess ? AppTheme.statusCompleted : AppTheme.statusFailed,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        _testResult!,
                        style: TextStyle(
                          color: _testSuccess ? AppTheme.statusCompleted : AppTheme.statusFailed,
                          fontSize: 12,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
            const SizedBox(height: 20),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: _testing ? null : _testConnection,
                    child: _testing
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Text('Test Connection'),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: ElevatedButton(
                    onPressed: _saveAndClose,
                    child: const Text('Save & Apply'),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _PresetChip extends StatelessWidget {
  final String label;
  final VoidCallback onTap;

  const _PresetChip({required this.label, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(8),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
        decoration: BoxDecoration(
          color: AppTheme.surfaceElevated,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: AppTheme.border),
        ),
        child: Text(
          label,
          style: const TextStyle(
            color: AppTheme.textSecondary,
            fontSize: 11,
            fontWeight: FontWeight.w500,
          ),
        ),
      ),
    );
  }
}
