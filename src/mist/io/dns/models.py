"""Definition of DNS Zone and Record mongoengine models"""

import re
import uuid
import ipaddress as ip

import mongoengine as me

from mist.io.clouds.models import Cloud
from mist.io.users.models import Organization
from mist.io.dns.controllers import ZoneController, RecordController
from mist.io.clouds.controllers.dns.base import BaseDNSController

from mist.io.exceptions import BadRequestError
from mist.io.exceptions import ZoneExistsError
from mist.io.exceptions import RequiredParameterMissingError

class Zone(me.Document):
    """This is the class definition for the Mongo Engine Document related to a
    DNS zone.
    """

    id = me.StringField(primary_key=True, default=lambda: uuid.uuid4().hex)
    owner = me.ReferenceField('Organization', required=True)

    zone_id = me.StringField(required=True)
    domain = me.StringField(required=True)
    type = me.StringField(required=True)
    ttl = me.IntField(required=True, default=0)
    extra = me.DictField()
    cloud = me.ReferenceField(Cloud, required=True,
                              reverse_delete_rule=me.CASCADE)

    meta = {
        'collection': 'zones',
        'indexes': [
            'owner',
            {
                'fields': ['cloud', 'zone_id'],
                'sparse': False,
                'unique': True,
                'cls': False,
            }
        ],
    }

    def __init__(self, *args, **kwargs):
        super(Zone, self).__init__(*args, **kwargs)
        self.ctl = ZoneController(self)

    @classmethod
    def add(cls, owner, cloud, id='', **kwargs):
        """Add Zone

        This is a class method, meaning that it is meant to be called on the
        class itself and not on an instance of the class.

        You're not meant to be calling this directly, but on a cloud subclass
        instead like this:

            zone = Zone.add(owner=org, domain='domain.com.')

        Params:
        - owner and domain are common and required params
        - only provide a custom zone id if you're migrating something
        - kwargs will be passed to appropriate controller, in most cases these
          should match the extra fields of the particular zone type.

        """
        if not kwargs['domain']:
            raise RequiredParameterMissingError('domain')
        if not cloud or not isinstance(cloud, Cloud):
            raise BadRequestError('cloud')
        if not owner or not isinstance(owner, Organization):
            raise BadRequestError('owner')
        zone = cls(owner=owner, cloud=cloud, domain=kwargs['domain'])
        if id:
            zone.id = id
        zone.ctl.create_zone(**kwargs)
        return zone

    def as_dict(self):
        """Return a dict with the model values."""
        return {
            'id': self.id,
            'zone_id': self.zone_id,
            'domain': self.domain,
            'type': self.type,
            'ttl': self.ttl,
            'extra': self.extra,
            'cloud': self.cloud.id
        }

    def clean(self):
        """Overriding the default clean method to implement param checking"""
        if not self.domain.endswith('.'):
            self.domain += "."

    def __str__(self):
        return 'Zone %s (%s/%s) of %s' % (self.id, self.zone_id, self.domain,
                                          self.owner)



class Record(me.Document):
    """This is the class definition for the Mongo Engine Document related to a
    DNS record.
    """

    id = me.StringField(primary_key=True, default=lambda: uuid.uuid4().hex)

    record_id = me.StringField(required=True)
    name = me.StringField(required=True)
    type = me.StringField(required=True)
    rdata = me.ListField(required=True)
    extra = me.DictField()
    ttl = me.IntField(default=0)
    # This ensures that any records that are under a zone are also deleted when
    # we delete the zone.
    zone = me.ReferenceField(Zone, required=True,
                             reverse_delete_rule=me.CASCADE)

    meta = {
        'collection': 'records',
        'indexes': [
            {
                'fields': ['zone', 'record_id'],
                'sparse': False,
                'unique': True,
                'cls': False,
            }
        ],
    }

    def __init__(self, *args, **kwargs):
        super(Record, self).__init__(*args, **kwargs)
        self.ctl = RecordController(self)

    @classmethod
    def add(cls, owner=None, zone=None, id='', **kwargs):
        """Add Record

        This is a class method, meaning that it is meant to be called on the
        class itself and not on an instance of the class.

        You're not meant to be calling this directly, but on a cloud subclass
        instead like this:

            record = Record.add(zone=zone, **kwargs)

        Params:
        - zone is a required param
        - only provide a custom record id if you're migrating something
        - kwargs will be passed to appropriate controller, in most cases these
          should match the extra fields of the particular record type.

        """
        if not kwargs['name']:
            raise RequiredParameterMissingError('name')
        if not kwargs['data']:
            raise RequiredParameterMissingError('data')
        if not kwargs['type']:
            raise RequiredParameterMissingError('type')
        # If we were not given a zone then we need the owner to try and find
        # the best matching domain.
        if not zone and kwargs['type'] in ['A', 'AAAA', 'CNAME']:
            assert isinstance(owner, Organization)
            zone = BaseDNSController.find_best_matching_zone(owner,
                                                             kwargs['name'])
        assert isinstance(zone, Zone)

        record = cls(zone=zone)
        if id:
            record.id = id
        record.ctl.create_record(**kwargs)
        return record

    def clean(self):
        """Overriding the default clean method to implement param checking"""
        # We need to be checking the rdata based on the type of record
        if self.type == 'A':
            try:
                ip_addr = self.rdata[0].decode('utf-8')
                ip.ip_address(ip_addr)
            except ValueError:
                raise me.ValidationError('IPv4 address provided is not valid')
        if self.type == 'AAAA':
            try:
                ip_addr = self.rdata[0].decode('utf-8')
                ip.ip_address(ip_addr)
            except ValueError:
                raise me.ValidationError('IPv6 address provided is not valid')
        if self.type == "CNAME":
            if not self.rdata[0].endswith('.'):
                self.rdata[0] += '.'
        if self.type == "A" or self.type == "AAAA" or self.type == "CNAME":
            if not len(self.rdata) == 1:
                raise me.ValidationError('We cannot have more than one rdata'
                                         'values for this type of record.')

    def __str__(self):
        return 'Record %s (name:%s, type:%s) of %s' % (
            self.id, self.name, self.type, self.zone.domain)

    def as_dict(self):
        """ Return a dict with the model values."""
        return {
            'id': self.id,
            'record_id': self.record_id,
            'name': self.name,
            'type': self.type,
            'rdata': self.rdata,
            'ttl': self.ttl,
            'extra': self.extra,
            'zone': self.zone.id
        }
