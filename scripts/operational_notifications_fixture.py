"""Test notification POSTs against a temporary local server only."""
import json
from threading import Thread
import unittest
from flask import Flask,request
from werkzeug.serving import make_server
from app.operational_notifications import OperationalNotifications, test_destination


class NotificationFixtureTests(unittest.TestCase):
    def setUp(self):
        self.received=[]
        receiver=Flask('disposable_notification_receiver')
        @receiver.route('/<kind>',methods=['GET','POST'])
        def receive(kind):
            self.received.append((kind,request.method,request.get_data(as_text=True),request.headers.get('Authorization')))
            if kind=='redirect':return '',302,{'Location':self.base+'/followed'}
            return ('',503) if kind=='failed' else ('',204)
        server=make_server('127.0.0.1',0,receiver,threaded=True)
        self.base='http://127.0.0.1:'+str(server.server_port)
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        def close():
            server.shutdown();thread.join(timeout=5);server.server_close()
        self.addCleanup(close)
        self.settings={'DRY_RUN':'true','NOTIFY_OPERATIONAL_FAILURES':'true','NOTIFY_ON_DRY_RUN':'true',
                       'NOTIFY_WEBHOOK_URL':self.base+'/webhook','JELLYFIN_API_TOKEN':'fixture-private-never-output'}
        self.alerts=OperationalNotifications()

    def test_disabled_and_preview_suppression_make_no_requests(self):
        self.settings['NOTIFY_OPERATIONAL_FAILURES']='false'
        self.assertEqual(self.alerts.emit(self.settings,'scan_blocked_or_uncertain')['status'],'disabled')
        self.settings.update(NOTIFY_OPERATIONAL_FAILURES='true',NOTIFY_ON_DRY_RUN='false')
        self.assertEqual(self.alerts.emit(self.settings,'scan_blocked_or_uncertain')['status'],'dry_run_suppressed')
        self.assertEqual(self.received,[])

    def test_three_protocols_only_receive_fixed_redacted_event(self):
        self.settings.update(NOTIFY_DISCORD_WEBHOOK_URL=self.base+'/discord',
            NOTIFY_NTFY_URL=self.base+'/ntfy',NOTIFY_NTFY_TOKEN='synthetic-ntfy-token')
        report=self.alerts.emit(self.settings,'scan_blocked_or_uncertain')
        self.assertEqual(report,{'status':'delivered','attempted':3,'delivered':3})
        for kind,method,body,auth in self.received:
            self.assertEqual(method,'POST');self.assertNotIn('fixture-private-never-output',body)
            self.assertNotIn(self.base,body)
            if kind=='discord':self.assertEqual(json.loads(body)['allowed_mentions'],{'parse':[]})
            if kind=='ntfy':self.assertEqual(auth,'Bearer synthetic-ntfy-token')
        generic=json.loads(next(row[2] for row in self.received if row[0]=='webhook'))
        self.assertFalse(generic['media_actions_authorized']);self.assertTrue(generic['preview'])
        self.assertEqual(self.alerts.emit(self.settings,'scan_blocked_or_uncertain')['status'],'suppressed')
        self.assertEqual(len(self.received),3)

    def test_manual_test_sends_only_to_selected_receiver(self):
        self.settings.update(NOTIFY_OPERATIONAL_FAILURES='false',
            NOTIFY_DISCORD_WEBHOOK_URL=self.base+'/discord')
        ok, _ = test_destination(self.settings, 'webhook')
        self.assertTrue(ok)
        self.assertEqual(len(self.received), 1)
        kind, method, body, _ = self.received[0]
        self.assertEqual((kind, method), ('webhook', 'POST'))
        self.assertEqual(json.loads(body)['event'], 'notification_test')
        self.assertNotIn('fixture-private-never-output', body)

    def test_failed_delivery_has_no_automatic_retry(self):
        self.settings['NOTIFY_WEBHOOK_URL']=self.base+'/failed'
        self.assertEqual(self.alerts.emit(self.settings,'settings_review_required')['status'],'delivery_failed')
        self.assertEqual(self.alerts.emit(self.settings,'settings_review_required')['status'],'suppressed')
        self.assertEqual(len(self.received),1)

    def test_redirect_does_not_forward_request_or_credentials(self):
        self.settings['NOTIFY_WEBHOOK_URL']=self.base+'/redirect'
        self.assertEqual(self.alerts.emit(self.settings,'settings_review_required')['status'],'delivery_failed')
        self.assertEqual([row[0] for row in self.received],['redirect'])

    def test_explicit_recovery_rearms_a_new_incident(self):
        self.alerts.emit(self.settings,'scan_blocked_or_uncertain')
        self.alerts.clear('scan_blocked_or_uncertain')
        self.alerts.emit(self.settings,'scan_blocked_or_uncertain')
        self.assertEqual(len(self.received),2)


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(NotificationFixtureTests))
    if not result.wasSuccessful():raise SystemExit(1)
    print(json.dumps({'status':'operational_notification_delivery_verified','tests':result.testsRun,
        'fixture_only':True,'external_delivery_performed':False,'production_services_changed':False,
        'media_actions_authorized':False}))
