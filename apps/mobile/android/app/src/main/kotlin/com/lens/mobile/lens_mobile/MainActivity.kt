package com.lens.mobile.lens_mobile

import android.content.Intent
import android.os.Bundle
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    companion object {
        private const val METHOD_CHANNEL = "com.lens.mobile/share_channel"
        private const val EVENT_CHANNEL = "com.lens.mobile/share_events"
        private const val MAX_TEXT_LENGTH = 1_000_000
        private const val KEY_LAUNCH_INTENT_CONSUMED = "com.lens.mobile.launch_intent_consumed"
    }

    private var initialShareData: Map<String, Any?>? = null
    private var eventSink: EventChannel.EventSink? = null
    private var isLaunchIntentConsumed = false
    private val pendingWarmShares = mutableListOf<Map<String, Any?>>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (savedInstanceState != null) {
            isLaunchIntentConsumed = savedInstanceState.getBoolean(KEY_LAUNCH_INTENT_CONSUMED, false)
        }
        if (!isLaunchIntentConsumed) {
            intent?.let { handleIntent(it, isInitial = true) }
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putBoolean(KEY_LAUNCH_INTENT_CONSUMED, isLaunchIntentConsumed)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIntent(intent, isInitial = false)
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)

        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, METHOD_CHANNEL)
            .setMethodCallHandler { call: MethodCall, result: MethodChannel.Result ->
                when (call.method) {
                    "getInitialShare" -> {
                        val data = initialShareData
                        initialShareData = null
                        isLaunchIntentConsumed = true
                        result.success(data)
                    }
                    "clearInitialShare" -> {
                        initialShareData = null
                        isLaunchIntentConsumed = true
                        result.success(true)
                    }
                    else -> result.notImplemented()
                }
            }

        EventChannel(flutterEngine.dartExecutor.binaryMessenger, EVENT_CHANNEL)
            .setStreamHandler(object : EventChannel.StreamHandler {
                override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
                    eventSink = events
                    if (events != null && pendingWarmShares.isNotEmpty()) {
                        for (item in pendingWarmShares) {
                            events.success(item)
                        }
                        pendingWarmShares.clear()
                    }
                }

                override fun onCancel(arguments: Any?) {
                    eventSink = null
                }
            })
    }

    private fun handleIntent(intent: Intent, isInitial: Boolean) {
        val action = intent.action
        val type = intent.type

        if ((Intent.ACTION_SEND == action || Intent.ACTION_SEND_MULTIPLE == action) && type != null) {
            // Strictly require text/plain or text/* MIME type consistent with AndroidManifest
            if (type == "text/plain" || type.startsWith("text/")) {
                val data = extractTextData(intent)
                if (data != null) {
                    if (isInitial) {
                        initialShareData = data
                        isLaunchIntentConsumed = true
                    } else {
                        if (eventSink != null) {
                            eventSink?.success(data)
                        } else {
                            pendingWarmShares.add(data)
                        }
                    }
                }
            }
        }
    }

    private fun extractTextData(intent: Intent): Map<String, Any?>? {
        val action = intent.action ?: return null

        // Explicit contract: LENS supports textual content only.
        // If EXTRA_STREAM is present (binary file, photo, media, or mixed stream+text payload),
        // reject immediately to avoid misleading, partial, or ambiguous text captures.
        if (intent.hasExtra(Intent.EXTRA_STREAM)) {
            return null
        }

        val subject = intent.getStringExtra(Intent.EXTRA_SUBJECT)
            ?: intent.getCharSequenceExtra(Intent.EXTRA_SUBJECT)?.toString()

        val text: String? = when (action) {
            Intent.ACTION_SEND -> {
                val raw = intent.getStringExtra(Intent.EXTRA_TEXT)
                    ?: intent.getCharSequenceExtra(Intent.EXTRA_TEXT)?.toString()
                if (raw != null && raw.length > MAX_TEXT_LENGTH) {
                    raw.substring(0, MAX_TEXT_LENGTH)
                } else {
                    raw
                }
            }
            Intent.ACTION_SEND_MULTIPLE -> {
                // Safeguard against Android 12 ClassCastException when non-CharSequence items exist
                val rawList: List<*>? = try {
                    val extra = intent.extras?.get(Intent.EXTRA_TEXT)
                    if (extra is List<*>) extra else null
                } catch (e: Exception) {
                    null
                }

                if (rawList != null) {
                    val builder = StringBuilder()
                    for (item in rawList) {
                        if (item !is CharSequence) continue
                        val str = item.toString().trim()
                        if (str.isEmpty()) continue
                        if (builder.isNotEmpty()) {
                            // Check if separator fits without exceeding max length
                            if (builder.length + 2 > MAX_TEXT_LENGTH) break
                            builder.append("\n\n")
                        }
                        val remainingCapacity = MAX_TEXT_LENGTH - builder.length
                        if (remainingCapacity <= 0) break
                        if (str.length > remainingCapacity) {
                            builder.append(str.substring(0, remainingCapacity))
                            break
                        } else {
                            builder.append(str)
                        }
                    }
                    if (builder.isNotEmpty()) {
                        builder.toString()
                    } else {
                        val raw = intent.getStringExtra(Intent.EXTRA_TEXT)
                            ?: intent.getCharSequenceExtra(Intent.EXTRA_TEXT)?.toString()
                        if (raw != null && raw.length > MAX_TEXT_LENGTH) {
                            raw.substring(0, MAX_TEXT_LENGTH)
                        } else {
                            raw
                        }
                    }
                } else {
                    val raw = intent.getStringExtra(Intent.EXTRA_TEXT)
                        ?: intent.getCharSequenceExtra(Intent.EXTRA_TEXT)?.toString()
                    if (raw != null && raw.length > MAX_TEXT_LENGTH) {
                        raw.substring(0, MAX_TEXT_LENGTH)
                    } else {
                        raw
                    }
                }
            }
            else -> null
        }

        if (text.isNullOrBlank()) {
            return null
        }

        val boundedSubject = if (subject != null && subject.length > 512) {
            subject.substring(0, 512)
        } else {
            subject
        }

        return mapOf(
            "action" to action,
            "text" to text,
            "subject" to boundedSubject,
            "timestamp" to System.currentTimeMillis()
        )
    }
}
