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
    }

    private var initialShareData: Map<String, Any?>? = null
    private var eventSink: EventChannel.EventSink? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        intent?.let { handleIntent(it, isInitial = true) }
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
                        result.success(data)
                    }
                    "clearInitialShare" -> {
                        initialShareData = null
                        result.success(true)
                    }
                    else -> result.notImplemented()
                }
            }

        EventChannel(flutterEngine.dartExecutor.binaryMessenger, EVENT_CHANNEL)
            .setStreamHandler(object : EventChannel.StreamHandler {
                override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
                    eventSink = events
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
            if (type.startsWith("text/")) {
                val data = extractTextData(intent)
                if (data != null) {
                    if (isInitial || eventSink == null) {
                        initialShareData = data
                    } else {
                        eventSink?.success(data)
                    }
                }
            }
        }
    }

    private fun extractTextData(intent: Intent): Map<String, Any?>? {
        val action = intent.action ?: return null
        val subject = intent.getStringExtra(Intent.EXTRA_SUBJECT)
            ?: intent.getCharSequenceExtra(Intent.EXTRA_SUBJECT)?.toString()

        val text: String? = when (action) {
            Intent.ACTION_SEND -> {
                intent.getStringExtra(Intent.EXTRA_TEXT)
                    ?: intent.getCharSequenceExtra(Intent.EXTRA_TEXT)?.toString()
            }
            Intent.ACTION_SEND_MULTIPLE -> {
                val list = intent.getCharSequenceArrayListExtra(Intent.EXTRA_TEXT)
                list?.filterNotNull()?.joinToString("\n") { it.toString() }
            }
            else -> null
        }

        if (text.isNullOrBlank()) {
            return null
        }

        val boundedText = if (text.length > MAX_TEXT_LENGTH) {
            text.substring(0, MAX_TEXT_LENGTH)
        } else {
            text
        }

        val boundedSubject = if (subject != null && subject.length > 512) {
            subject.substring(0, 512)
        } else {
            subject
        }

        return mapOf(
            "action" to action,
            "text" to boundedText,
            "subject" to boundedSubject,
            "timestamp" to System.currentTimeMillis()
        )
    }
}
