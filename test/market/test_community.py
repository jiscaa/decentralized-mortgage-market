import datetime
import unittest
from twisted.python.threadable import registerAsIOThread

from mock import Mock

from dispersy.candidate import LoopbackCandidate
from dispersy.dispersy import Dispersy
from dispersy.endpoint import ManualEnpoint
from dispersy.member import DummyMember, Member
from market.api.api import MarketAPI, STATUS
from market.community.community import MortgageMarketCommunity
from market.community.conversion import MortgageMarketConversion
from market.community.payload import SignedConfirmPayload
from market.database.backends import MemoryBackend
from market.database.database import MockDatabase
from market.models import DatabaseModel
from market.models.house import House
from market.models.loans import LoanRequest, Mortgage, Campaign
from market.models.profiles import BorrowersProfile
from market.models.user import User


class FakeMessage(object):
    def __init__(self, payload):
        self.payload = payload


class FakePayload(object):
    request = ''
    fields = []
    models = {}


class CommunityTestSuite(unittest.TestCase):
    """Conversion test cases."""

    def setUp(self):
        # Faking IOThread
        registerAsIOThread()

        # Object creation and preperation
        self.dispersy = Dispersy(ManualEnpoint(0), unicode("dispersy_temporary"))
        self.dispersy_bank = Dispersy(ManualEnpoint(0), unicode("dispersy_temporary2"))
        self.dispersy_investor = Dispersy(ManualEnpoint(0), unicode("dispersy_temporary3"))

        # a neutral api to generate the intial id's for loan requests and such to skip
        # having to save the loan request to the (sending) user from each test as that
        # isn't relevant.
        self.neutral_api = MarketAPI(MockDatabase(MemoryBackend()))

        self.api = MarketAPI(MockDatabase(MemoryBackend()))
        self.api_bank = MarketAPI(MockDatabase(MemoryBackend()))
        self.api_investor = MarketAPI(MockDatabase(MemoryBackend()))

        self.api.db.backend.clear()
        self.api_bank.db.backend.clear()
        self.api_investor.db.backend.clear()

        self.user, _, priv_user = self.api.create_user()
        self.bank, _, priv_bank = self.api.create_user()
        self.investor, _, priv_investor = self.api.create_user()

        # save the user to the bank and investor db
        self.user.post_or_put(self.api_bank.db)
        self.bank.post_or_put(self.api_bank.db)
        self.investor.post_or_put(self.api_bank.db)

        self.user.post_or_put(self.api_investor.db)
        self.bank.post_or_put(self.api_investor.db)
        self.investor.post_or_put(self.api_investor.db)

        self.dispersy._database.open()
        self.dispersy_bank._database.open()
        self.dispersy_investor._database.open()

        self.master_member = DummyMember(self.dispersy, 1, "a" * 20)

        self.member = self.dispersy.get_member(private_key=priv_user.decode("HEX"))
        self.member_bank = self.dispersy.get_member(private_key=priv_bank.decode("HEX"))
        self.member_investor = self.dispersy.get_member(private_key=priv_investor.decode("HEX"))

        self.community = MortgageMarketCommunity.init_community(self.dispersy, self.master_member, self.member)
        self.community_bank = MortgageMarketCommunity.init_community(self.dispersy_bank, self.master_member, self.member_bank)
        self.community_investor = MortgageMarketCommunity.init_community(self.dispersy_investor, self.master_member, self.member_investor)

        self.community.api = self.api
        self.community.user = self.user
        self.api.community = self.community

        self.community_bank.api = self.api_bank
        self.community_bank.user = self.bank
        self.api.community = self.community_bank

        self.community_investor.api = self.api_investor
        self.community_investor.user = self.investor
        self.api.community = self.community_investor

        # Add our conversion to the community.
        self.conversion = MortgageMarketConversion(self.community)

        self.setupModels()

    def setupModels(self):
        self.house = House('2500AA', '34', 'Aa Weg', 1000)
        self.house.post_or_put(self.neutral_api.db)

        self.loan_request = LoanRequest(user_key=self.user.id,
                                        house_id=self.house.id,
                                        house_link='http://www.example.com',
                                        seller_phone_number='06000000',
                                        seller_email='example@email.com',
                                        mortgage_type=1,
                                        banks=[self.bank.id],
                                        description=u'Unicode description',
                                        amount_wanted=10000,
                                        status={}
                                        )
        self.loan_request.post_or_put(self.neutral_api.db)
        self.profile = BorrowersProfile(first_name=u'Jebediah', last_name=u'Kerman', email='exmaple@asdsa.com', iban='sadasdas',
                                        phone_number='213131', current_postal_code='2312AA',
                                        current_house_number='2132', current_address='Damstraat 1', document_list=[])
        self.profile.post_or_put(self.neutral_api.db)

        self.mortgage = Mortgage(
            request_id=self.loan_request.id,
            house_id=self.house.id,
            bank=self.bank.id,
            amount=10000,
            mortgage_type=1,
            interest_rate=1.0,
            max_invest_rate=2.0,
            default_rate=3.0,
            duration=60,
            risk='A',
            investors=[],
            status=STATUS.PENDING
        )
        self.mortgage.post_or_put(self.neutral_api.db)

        self.campaign = Campaign(mortgage_id=self.mortgage.id, amount=self.mortgage.amount, end_date=datetime.datetime.now(),
                                 completed=False)
        self.campaign.post_or_put(self.neutral_api.db)

    def isModelInDB(self, api, model):
        return not api.db.get(model.type, model.id) is None

    def remove_from_db(self, model):
        self.api.db.backend.delete(model)

    def remove_payload_models_from_db(self, payload):
        for key in payload.models:
            self.remove_from_db(payload.models[key])

    def test_init(self):
        self.assertIsInstance(self.conversion, MortgageMarketConversion)
        self.assertIsInstance(self.community, MortgageMarketCommunity)
        self.assertIsInstance(self.user, User)
        self.assertIsInstance(self.member, Member)
        self.assertEqual(self.user.id, self.member.public_key.encode("HEX"))

    def test_on_loan_request_receive(self):
        """
        Test a user sending a loan request to a bank

        user --> bank
        """
        payload = FakePayload()
        payload.request = u"loan_request"
        payload.models = {self.house.type: self.house, self.loan_request.type: self.loan_request,
                          self.user.type: self.user, self.profile.type: self.profile}

        # Bank doesn't have them yet
        self.assertFalse(self.isModelInDB(self.api_bank, self.loan_request))
        self.assertFalse(self.isModelInDB(self.api_bank, self.profile))
        self.assertFalse(self.isModelInDB(self.api_bank, self.house))

        self.community_bank.on_loan_request_receive(payload)

        self.assertTrue(self.isModelInDB(self.api_bank, self.loan_request))
        self.assertTrue(self.isModelInDB(self.api_bank, self.profile))
        self.assertTrue(self.isModelInDB(self.api_bank, self.house))

    def test_on_loan_request_reject(self):
        """
        Test a bank rejecting a users loan_request

        bank --> user
        """
        # Save the user-side initial data which is a pending loan request.
        self.loan_request.status[self.bank.id] = STATUS.PENDING
        self.user.loan_request_ids.append(self.loan_request.id)
        self.user.post_or_put(self.api.db)

        self.assertIn(self.loan_request.id, self.user.loan_request_ids)

        # Deep copy the loan request
        loan_request_bank = DatabaseModel.decode(self.loan_request.encode())
        loan_request_bank.status[self.bank.id] = STATUS.REJECTED

        # Make the payload
        payload = FakePayload()
        payload.request = u"loan_request_reject"
        payload.models = {self.loan_request.type: loan_request_bank,
                          self.user.type: self.bank}

        self.community.on_loan_request_reject(payload)

        # Now let's pull the loan request from the user database
        self.assertTrue(self.isModelInDB(self.api, loan_request_bank))
        loan_request = self.api.db.get(loan_request_bank.type, loan_request_bank.id)

        self.assertEqual(loan_request.status[self.bank.id], STATUS.REJECTED)
        self.assertNotIn(self.loan_request.id, self.user.loan_request_ids)

    def test_on_mortgage_offer(self):
        """
        Test a bank sending a mortgage offer to a user

        bank -> user
        """
        payload = FakePayload()
        payload.request = u"mortgage_offer"
        payload.models = {self.loan_request.type: self.loan_request,
                          self.mortgage.type: self.mortgage}
        self.loan_request.status[self.bank.id] = STATUS.ACCEPTED
        self.mortgage.status = STATUS.ACCEPTED

        self.assertFalse(self.isModelInDB(self.api, self.loan_request))
        self.assertFalse(self.isModelInDB(self.api, self.mortgage))

        self.community.on_mortgage_offer(payload)

        # The user now has the models.
        self.assertTrue(self.isModelInDB(self.api, self.loan_request))
        self.assertTrue(self.isModelInDB(self.api, self.mortgage))

        # Check if the mortgage id is in the user
        self.user.update(self.api.db)
        self.assertIn(self.mortgage.id, self.user.mortgage_ids)
        self.assertEqual(self.api.db.get(self.mortgage.type, self.mortgage.id).status, STATUS.ACCEPTED)

    def test_on_mortgage_accept(self):
        """
        Test a user accepting a mortgage

        user -> bank
        user -> investor
        """
        payload = FakePayload()
        payload.request = u"mortgage_offer"
        payload.models = {self.loan_request.type: self.loan_request,
                          self.mortgage.type: self.mortgage,
                          self.user.type: self.user,
                          self.campaign.type: self.campaign,
                          }
        self.loan_request.status[self.bank.id] = STATUS.ACCEPTED
        self.mortgage.status = STATUS.ACCEPTED
        self.user.campaign_ids.append(self.campaign.id)
        self.user.mortgage_ids.append(self.mortgage.id)
        self.user.loan_request_ids.append(self.loan_request.id)

        self.community_bank.on_mortgage_accept_signed(payload)
        self.community_investor.on_mortgage_accept_unsigned(payload)

        # The bank now has the models.
        self.assertTrue(self.isModelInDB(self.api_bank, self.mortgage))
        self.assertTrue(self.isModelInDB(self.api_bank, self.campaign))
        # The loan request isn't sent to the bank
        self.assertFalse(self.isModelInDB(self.api_bank, self.loan_request))

        # The investor has the models.
        self.assertTrue(self.isModelInDB(self.api_investor, self.loan_request))
        self.assertTrue(self.isModelInDB(self.api_investor, self.mortgage))
        self.assertTrue(self.isModelInDB(self.api_investor, self.campaign))

        # And knowledge of the campaign.
        user_from_inv_db = self.api_investor.db.get(self.user.type, self.user.id)
        self.assertIn(self.campaign.id, user_from_inv_db.campaign_ids)

        # Check of the campaign has been added to the bank
        self.bank.update(self.api_bank.db)
        self.assertIn(self.campaign.id, self.bank.campaign_ids)


    def tearDown(self):
        # Closing and unlocking dispersy database for other tests in test suite
        self.dispersy._database.close()
        self.dispersy_bank._database.close()
        self.dispersy_investor._database.close()


class IncomingQueueTestCase(unittest.TestCase):
    def setUp(self):
        self.api = MarketAPI(MockDatabase(MemoryBackend()))
        mock = Mock()
        self.api.community = mock

        mock.on_loan_request_receive.return_value = True
        mock.on_loan_request_reject.return_value = True
        mock.on_mortgage_accept_signed.return_value = True
        mock.on_mortgage_accept_unsigned.return_value = True
        mock.on_investment_accept.return_value = True
        mock.on_mortgage_reject.return_value = True
        mock.on_investment_reject.return_value = True
        mock.on_mortgage_offer.return_value = True
        mock.on_investment_offer.return_value = True

    def test_incoming_loan_request(self):
        payload = FakePayload()
        payload.request = u"loan_request"
        payload.models = {}

        message = FakeMessage(payload)

        self.api.incoming_queue._queue.append(message)
        self.api.incoming_queue.process()

        self.assertTrue(self.api.community.on_loan_request_receive.called)

    def test_incoming_loan_request_reject(self):
        payload = FakePayload()
        payload.request = u"loan_request_reject"
        payload.models = {}

        message = FakeMessage(payload)

        self.api.incoming_queue._queue.append(message)
        self.api.incoming_queue.process()

        self.assertTrue(self.api.community.on_loan_request_reject.called)

    def test_incoming_mortgage_accept_signed(self):
        payload = FakePayload()
        payload.request = u"mortgage_accept_signed"
        payload.models = {}

        message = FakeMessage(payload)

        self.api.incoming_queue._queue.append(message)
        self.api.incoming_queue.process()

        self.assertTrue(self.api.community.on_mortgage_accept_signed.called)

    def test_incoming_mortgage_accept_unsigned(self):
        payload = FakePayload()
        payload.request = u"mortgage_accept_unsigned"
        payload.models = {}

        message = FakeMessage(payload)

        self.api.incoming_queue._queue.append(message)
        self.api.incoming_queue.process()

        self.assertTrue(self.api.community.on_mortgage_accept_unsigned.called)

    def test_incoming_investment_accept(self):
        payload = FakePayload()
        payload.request = u"investment_accept"
        payload.models = {}

        message = FakeMessage(payload)

        self.api.incoming_queue._queue.append(message)
        self.api.incoming_queue.process()

        self.assertTrue(self.api.community.on_investment_accept.called)

    def test_incoming_investment_offer(self):
        payload = FakePayload()
        payload.request = u"investment_offer"
        payload.models = {}

        message = FakeMessage(payload)

        self.api.incoming_queue._queue.append(message)
        self.api.incoming_queue.process()

        self.assertTrue(self.api.community.on_investment_offer.called)

    def test_incoming_investment_reject(self):
        payload = FakePayload()
        payload.request = u"investment_reject"
        payload.models = {}

        message = FakeMessage(payload)

        self.api.incoming_queue._queue.append(message)
        self.api.incoming_queue.process()

        self.assertTrue(self.api.community.on_investment_reject.called)

    def test_incoming_mortgage_reject(self):
        payload = FakePayload()
        payload.request = u"mortgage_reject"
        payload.models = {}

        message = FakeMessage(payload)

        self.api.incoming_queue._queue.append(message)
        self.api.incoming_queue.process()

        self.assertTrue(self.api.community.on_mortgage_reject.called)

    def test_incoming_mortgage_offer(self):
        payload = FakePayload()
        payload.request = u"mortgage_offer"
        payload.models = {}

        message = FakeMessage(payload)

        self.api.incoming_queue._queue.append(message)
        self.api.incoming_queue.process()

        self.assertTrue(self.api.community.on_mortgage_offer.called)


class OutgoingQueueTestCase(unittest.TestCase):
    def setUp(self):
        self.api = MarketAPI(MockDatabase(MemoryBackend()))
        mock = Mock()
        self.api.community = mock

        mock.send_api_message_candidate.return_value = True
        mock.send_api_message_community.return_value = True

    def test_send_community_message(self):
        request = u'mortgage_offer'
        fields = ['int']
        models = {'int': 4}
        receivers = []

        self.api.outgoing_queue.push((request, fields, models, receivers))

        # Not called yet
        self.assertFalse(self.api.community.send_api_message_community.called)

        self.api.outgoing_queue.process()

        self.assertTrue(self.api.community.send_api_message_community.called)
        self.api.community.send_api_message_community.assert_called_with(request, fields, models)

    def test_send_candidate_message(self):
        fake_user = User('ss', 1)
        fake_user2 = User('ss2', 2)
        fake_candidate = 'bob_candidate'

        self.api.user_candidate[fake_user.id] = fake_candidate

        request = u'mortgage_offer'
        fields = ['int']
        models = {'int': 4}
        receivers = [fake_user, fake_user2]

        self.api.outgoing_queue.push((request, fields, models, receivers))

        # Not called yet
        self.assertFalse(self.api.community.send_api_message_candidate.called)

        self.api.outgoing_queue.process()

        self.assertTrue(self.api.community.send_api_message_candidate.called)
        self.api.community.send_api_message_candidate.assert_called_with(request, fields, models, tuple([fake_candidate]))

        # Confirm that the message is still in the queue since fake_user2 has no candidate.
        self.assertIn((request, fields, models, receivers), self.api.outgoing_queue._queue)

        # Reset for the next part
        self.api.community.reset_mock()
        self.assertFalse(self.api.community.send_api_message_candidate.called)

        # Add a candidate for fake_user2 and process messages
        fake_candidate2 = 'bob_candidate2'
        self.api.user_candidate[fake_user2.id] = fake_candidate2
        self.api.outgoing_queue.process()

        self.assertTrue(self.api.community.send_api_message_candidate.called)
        self.api.community.send_api_message_candidate.assert_called_with(request, fields, models, tuple([fake_candidate2]))

        # Confirm that the message is gone
        self.assertNotIn((request, fields, models, receivers), self.api.outgoing_queue._queue)


class ConversionTestCase(unittest.TestCase):
    def setUp(self):
        # Faking IOThread
        registerAsIOThread()

        # Object creation and preperation
        self.dispersy = Dispersy(ManualEnpoint(0), unicode("dispersy_temporary"))
        self.api = MarketAPI(MockDatabase(MemoryBackend()))
        self.api.db.backend.clear()

        user, _, priv = self.api.create_user()
        self.bank, _, _ = self.api.create_user()
        self.user = user
        self.private_key = priv

        self.dispersy._database.open()
        self.master_member = DummyMember(self.dispersy, 1, "a" * 20)
        self.member = self.dispersy.get_member(private_key=self.private_key.decode("HEX"))
        self.community = MortgageMarketCommunity.init_community(self.dispersy, self.master_member, self.member)

        self.community.api = self.api
        self.community.user = self.user
        self.api.community = self.community

        # Add our conversion to the community.
        self.conversion = MortgageMarketConversion(self.community)
        self.community._conversions = []
        self.community.add_conversion(self.conversion)

        self.setupModels()

    def setupModels(self):
        self.house = House('2500AA', '34', 'Aa Weg', 1000)
        self.house.post_or_put(self.api.db)

        self.loan_request = LoanRequest(user_key=self.user.id,
                                        house_id=self.house.id,
                                        house_link='http://www.example.com',
                                        seller_phone_number='06000000',
                                        seller_email='example@email.com',
                                        mortgage_type=1,
                                        banks=[self.bank.id],
                                        description=u'Unicode description',
                                        amount_wanted=10000,
                                        status={}
                                        )
        self.loan_request.post_or_put(self.api.db)
        self.profile = BorrowersProfile(first_name=u'Jebediah', last_name=u'Kerman', email='exmaple@asdsa.com', iban='sadasdas',
                                        phone_number='213131', current_postal_code='2312AA',
                                        current_house_number='2132', current_address='Damstraat 1', document_list=[])
        self.profile.post_or_put(self.api.db)

    def test_encode_introduce_user(self):
        meta = self.community.get_meta_message(u"introduce_user")
        message = meta.impl(authentication=(self.member,),
                            distribution=(self.community.claim_global_time(),),
                            payload=([self.user.type], {self.user.type: self.user}),
                            destination=(LoopbackCandidate(),))

        encoded_message = self.conversion._encode_model(message)[0]
        decoded_payload = self.conversion._decode_model(message, 0, encoded_message)[1]

        self.assertEqual(message.payload.fields, decoded_payload.fields)
        self.assertEqual(message.payload.models, decoded_payload.models)

    def test_encode_model_request(self):
        meta = self.community.get_meta_message(u"model_request")
        message = meta.impl(authentication=(self.member,),
                            distribution=(self.community.claim_global_time(),),
                            payload=(['boo', 'baa'],),
                            destination=(LoopbackCandidate(),))

        encoded_message = self.conversion._encode_model_request(message)[0]
        decoded_payload = self.conversion._decode_model_request(message, 0, encoded_message)[1]

        self.assertEqual(message.payload.models, decoded_payload.models)

    def test_encode_api_request_community(self):
        meta = self.community.get_meta_message(u"api_message_community")
        message = meta.impl(authentication=(self.member,),
                            distribution=(self.community.claim_global_time(), meta.distribution.claim_sequence_number()),
                            payload=(u"unicode_message", [self.user.type], {self.user.type: self.user},),
                            destination=(LoopbackCandidate(),))

        encoded_message = self.conversion._encode_api_message(message)[0]
        decoded_payload = self.conversion._decode_api_message(message, 0, encoded_message)[1]

        self.assertEqual(message.payload.models, decoded_payload.models)

    def test_encode_api_request_candidate(self):
        meta = self.community.get_meta_message(u"api_message_candidate")
        message = meta.impl(authentication=(self.member,),
                            distribution=(self.community.claim_global_time(),),
                            payload=(u"unicode_message", [self.user.type], {self.user.type: self.user},),
                            destination=(LoopbackCandidate(),))

        encoded_message = self.conversion._encode_api_message(message)[0]
        decoded_payload = self.conversion._decode_api_message(message, 0, encoded_message)[1]

        self.assertEqual(message.payload.models, decoded_payload.models)

    def test_encode_signed_confirm(self):
        payload_list = []
        for k in range(1, 12):
            payload_list.append(None)

        payload_list[0] = self.user.id  # benefactor, 0
        payload_list[1] = self.bank.id  # beneficiary, 1
        payload_list[2] = self.loan_request
        payload_list[3] = None  # agreement beneficiary
        payload_list[4] = 0
        payload_list[5] = 0  # sequence number beneficiary
        payload_list[6] = 'hashsas'
        payload_list[7] = 'asdasdas'  # previous hash beneficiary
        payload_list[8] = 'sig1'  # Signature benefactor
        payload_list[9] = 'sig2'  # Signature beneficiary
        payload_list[10] = 324325252

        meta = self.community.get_meta_message(u"signed_confirm")
        loop = LoopbackCandidate()
        message = meta.impl(authentication=([self.member, self.member],),
                            distribution=(self.community.claim_global_time(),),
                            payload=tuple(payload_list))

        encoded_message = self.conversion._encode_signed_confirm(message)[0]
        decoded_payload = self.conversion._decode_signed_confirm(message, 0, encoded_message)[1]

        p1 = message.payload
        p2 = decoded_payload

        assert isinstance(p1, SignedConfirmPayload.Implementation)
        assert isinstance(p2, SignedConfirmPayload.Implementation)

        self.assertEqual(p1.agreement_benefactor, p2.agreement_benefactor)
        self.assertEqual(p1.agreement_beneficiary, p2.agreement_beneficiary)
        self.assertEqual(p1.benefactor, p2.benefactor)
        self.assertEqual(p1.beneficiary, p2.beneficiary)
        self.assertEqual(p1.previous_hash_benefactor, p2.previous_hash_benefactor)
        self.assertEqual(p1.previous_hash_beneficiary, p2.previous_hash_beneficiary)
        self.assertEqual(p1.sequence_number_benefactor, p2.sequence_number_benefactor)
        self.assertEqual(p1.sequence_number_beneficiary, p2.sequence_number_beneficiary)
        self.assertEqual(p1.signature_beneficiary, p2.signature_beneficiary)
        self.assertEqual(p1.signature_benefactor, p1.signature_benefactor)
        self.assertEqual(p1.time, p2.time)


if __name__ == '__main__':
    unittest.main()
