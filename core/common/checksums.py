import hashlib
import json
from uuid import UUID

from django.conf import settings
from django.db import models
from pydash import get

from core.common.utils import generic_sort
from core.toggles.models import Toggle


class ChecksumModel(models.Model):
    class Meta:
        abstract = True

    checksums = models.JSONField(null=True, blank=True, default=dict)

    CHECKSUM_EXCLUSIONS = []
    CHECKSUM_INCLUSIONS = []
    STANDARD_CHECKSUM_KEY = 'standard'
    SMART_CHECKSUM_KEY = 'smart'

    def get_checksums(self, queue=False, recalculate=False):
        _checksums = None
        if Toggle.get('CHECKSUMS_TOGGLE'):
            if not recalculate and self.checksums and self.has_all_checksums():
                _checksums = self.checksums
            elif queue:
                self.queue_checksum_calculation()
                _checksums = self.checksums or {}
            else:
                self.set_checksums()
                _checksums = self.checksums
        return _checksums

    def queue_checksum_calculation(self):
        from core.common.tasks import calculate_checksums
        if get(settings, 'TEST_MODE', False):
            calculate_checksums(self.__class__.__name__, self.id)
            self.refresh_from_db()
        else:
            calculate_checksums.apply_async((self.__class__.__name__, self.id), queue='default', permanent=False)

    def has_all_checksums(self):
        return self.has_standard_checksum() and self.has_smart_checksum()

    def has_standard_checksum(self):
        return self.STANDARD_CHECKSUM_KEY in self.checksums if self.STANDARD_CHECKSUM_KEY else True

    def has_smart_checksum(self):
        return self.SMART_CHECKSUM_KEY in self.checksums if self.SMART_CHECKSUM_KEY else True

    def set_checksums(self):
        if Toggle.get('CHECKSUMS_TOGGLE'):
            self.checksums = self._calculate_checksums()
            self.save(update_fields=['checksums'])

    @property
    def checksum(self):
        """Returns the checksum of the model instance or standard only checksum."""
        _checksum = None
        if Toggle.get('CHECKSUMS_TOGGLE'):
            if get(self, f'checksums.{self.STANDARD_CHECKSUM_KEY}'):
                _checksum = self.checksums[self.STANDARD_CHECKSUM_KEY]
            else:
                self.get_checksums()
                _checksum = self.checksums.get(self.STANDARD_CHECKSUM_KEY)
        return _checksum

    def get_checksum_fields(self):
        return {field: getattr(self, field) for field in self.CHECKSUM_INCLUSIONS}

    def get_standard_checksum_fields(self):
        return self.get_checksum_fields()

    def get_smart_checksum_fields(self):
        return {}

    def get_all_checksums(self):
        checksums = None
        if Toggle.get('CHECKSUMS_TOGGLE'):
            checksums = {}
            if self.STANDARD_CHECKSUM_KEY:
                checksums[self.STANDARD_CHECKSUM_KEY] = self._calculate_standard_checksum()
            if self.SMART_CHECKSUM_KEY:
                checksums[self.SMART_CHECKSUM_KEY] = self._calculate_smart_checksum()
        return checksums

    @staticmethod
    def generate_checksum(data):
        return Checksum.generate(ChecksumModel._cleanup(data))

    @staticmethod
    def generate_checksum_from_many(data):
        checksums = [
            Checksum.generate(ChecksumModel._cleanup(_data)) for _data in data
        ] if isinstance(data, list) else [
            Checksum.generate(ChecksumModel._cleanup(data))
        ]
        if len(checksums) == 1:
            return checksums[0]
        return Checksum.generate(checksums)

    def _calculate_standard_checksum(self):
        fields = self.get_standard_checksum_fields()
        return None if fields is None else self.generate_checksum(fields)

    def _calculate_smart_checksum(self):
        fields = self.get_smart_checksum_fields()
        return self.generate_checksum(fields) if fields else None

    @staticmethod
    def _cleanup(fields):
        result = fields
        if isinstance(fields, dict):  # pylint: disable=too-many-nested-blocks
            result = {}
            for key, value in fields.items():
                if value is None:
                    continue
                if key in ['retired'] and not value:
                    continue
                if key in ['is_active'] and value:
                    continue
                if key in ['extras']:
                    if not value:
                        continue
                    if isinstance(value, dict) and any(key.startswith('__') for key in value):
                        value_copied = value.copy()
                        for extra_key in value:
                            if extra_key.startswith('__'):
                                value_copied.pop(extra_key)
                        value = value_copied
                result[key] = value
        return result

    def _calculate_checksums(self):
        return self.get_all_checksums()


class Checksum:
    @classmethod
    def generate(cls, obj, hash_algorithm='MD5'):
        # hex encoding is used to make the hash more readable
        serialized_obj = cls._serialize(obj).encode('utf-8')
        hash_func = hashlib.new(hash_algorithm)
        hash_func.update(serialized_obj)

        return hash_func.hexdigest()

    @classmethod
    def _serialize(cls, obj):
        if isinstance(obj, list) and len(obj) == 1:
            obj = obj[0]
        if isinstance(obj, list):
            return f"[{','.join(map(cls._serialize, generic_sort(obj)))}]"
        if isinstance(obj, dict):
            keys = generic_sort(obj.keys())
            acc = f"{{{json.dumps(keys)}"
            for key in keys:
                acc += f"{cls._serialize(obj[key])},"
            return f"{acc}}}"
        if isinstance(obj, UUID):
            return json.dumps(str(obj))
        return json.dumps(obj)


class ChecksumDiff:  # pragma: no cover
    def __init__(self, resources1, resources2, identity='mnemonic', verbosity=0):  # pylint: disable=too-many-arguments
        self.resources1 = resources1
        self.resources2 = resources2
        self.identity = identity
        self.verbosity = verbosity
        self.same = {}
        self.same_smart = {}
        self.changed_smart = {}
        self.changed_standard = {}
        self.result = {}
        self._resources1_map = None
        self._resources1_map_retired = None
        self._resources2_map = None
        self._resources2_map_retired = None
        self._resources1_set = None
        self._resources1_set_retired = None
        self._resources2_set = None
        self._resources2_set_retired = None
        self._retired = None

    def get_resources_map(self, resources):
        return {
            'active': self._get_resource_map(resources.filter(retired=False)),
            'retired': self._get_resource_map(resources.filter(retired=False))
        }

    def _get_resource_map(self, resources):
        return {
            get(resource, self.identity): {
                'checksums': resource.checksums,
                'id': resource.id
            } for resource in resources
        }

    @property
    def resources1_map(self):
        if self._resources1_map is not None:
            return self._resources1_map
        resources_map = self.get_resources_map(self.resources1)
        self._resources1_map = resources_map['active']
        self._resources1_map_retired = resources_map['retired']
        return self._resources1_map

    @property
    def resources1_map_retired(self):
        if self._resources1_map_retired is not None:
            return self._resources1_map_retired
        resources_map = self.get_resources_map(self.resources1)
        self._resources1_map = resources_map['active']
        self._resources1_map_retired = resources_map['retired']
        return self._resources1_map_retired

    @property
    def resources2_map(self):
        if self._resources2_map is not None:
            return self._resources2_map
        resources_map = self.get_resources_map(self.resources2)
        self._resources2_map = resources_map['active']
        self._resources2_map_retired = resources_map['retired']
        return self._resources2_map

    @property
    def resources2_map_retired(self):
        if self._resources2_map_retired is not None:
            return self._resources2_map_retired
        resources_map = self.get_resources_map(self.resources2)
        self._resources2_map = resources_map['active']
        self._resources2_map_retired = resources_map['retired']
        return self._resources2_map_retired

    @property
    def resources1_set(self):
        if self._resources1_set is not None:
            return self._resources1_set
        self._resources1_set = set(self.resources1_map.keys())
        return self._resources1_set

    @property
    def resources1_set_retired(self):
        if self._resources1_set_retired is not None:
            return self._resources1_set_retired
        self._resources1_set_retired = set(self.resources1_map_retired.keys())
        return self._resources1_set_retired

    @property
    def resources2_set(self):
        if self._resources2_set is not None:
            return self._resources2_set
        self._resources2_set = set(self.resources2_map.keys())
        return self._resources2_set

    @property
    def resources2_set_retired(self):
        if self._resources2_set_retired is not None:
            return self._resources2_set_retired
        self._resources2_set_retired = set(self.resources2_map_retired.keys())
        return self._resources2_set_retired

    @property
    def new(self):
        return {key: self.resources1_map[key] for key in self.resources1_set - self.resources2_set}

    @property
    def deleted(self):
        diff_set = self.resources2_set - self.resources1_set
        return {key: self.resources2_map[key] for key in diff_set if key not in self.retired}

    @property
    def retired(self):
        if self._retired is not None:
            return self._retired
        self._retired = {
            key: self.resources2_map_retired[key] for key in self.resources2_set_retired - self.resources1_set_retired}
        return self._retired

    @property
    def common(self):
        return {key: self.resources1_map[key] for key in self.resources1_set & self.resources2_set}

    @property
    def is_verbose(self):
        return self.verbosity >= 1

    @property
    def is_very_verbose(self):
        return self.verbosity == 2

    @property
    def include_same(self):
        return self.is_verbose

    def populate_diff_from_common(self):
        common = self.common
        resources1_map = self.resources1_map
        resources2_map = self.resources2_map

        for key, info in common.items():
            checksums1 = resources1_map[key]['checksums']
            checksums2 = resources2_map[key]['checksums']
            if checksums1['standard'] != checksums2['standard']:
                self.changed_standard[key] = info
            elif self.include_same:
                self.same[key] = info
            if checksums1['smart'] != checksums2['smart']:
                self.changed_smart[key] = info
            elif self.include_same:
                self.same_smart[key] = info

    def get_struct(self, values):
        total = len(values or [])
        if self.is_very_verbose:
            if values:
                return {'total': total, self.identity: list(values.keys())}
            return total

        return total

    def prepare(self):
        self.result = {
            'new': self.get_struct(self.new),
            'removed': self.get_struct(self.deleted),
            'retired': self.get_struct(self.retired),
            'changed': self.get_struct(self.changed_standard),
            'smart_changed': self.get_struct(self.changed_smart),
        }
        if self.include_same:
            self.result['same'] = self.get_struct(self.same)
            self.result['smart_same'] = self.get_struct(self.same_smart)

    def process(self, refresh=False):
        if refresh:
            self.result = {}
        if self.result:
            return self.result

        self.populate_diff_from_common()
        self.prepare()

        return self.result

    def pretty_print_dict(self, d, indent=0):  # pragma: no cover
        res = ""
        for k, v in d.items():
            res += "\t" * indent + str(k) + "\n"
            if isinstance(v, dict):
                res += self.pretty_print_dict(v, indent + 1)
            else:
                res += "\t" * (indent + 1) + str(v) + "\n"
        return res

    def print(self):
        print(self.pretty_print_dict(self.result))

    def get_db_id_for(self, diff_key, identity):
        if diff_key == 'retired':
            return get(
                self.resources1_map_retired, f'{identity}.id'
            ) or self.resources2_map_retired[identity]['id']
        return get(
            self.resources1_map, f'{identity}.id'
        ) or self.resources2_map[identity]['id']


class ChecksumChangelog:  # pragma: no cover
    def __init__(self, version1, version2, concepts_diff, mappings_diff, identity='mnemonic'):  # pylint: disable=too-many-arguments
        self.version1 = version1
        self.version2 = version2
        self.concepts_diff = concepts_diff
        self.mappings_diff = mappings_diff
        self.identity = identity
        self.result = {}

    def get_mapping_summary(self, mapping, mapping_id=None):
        return {
            'id': mapping_id or get(mapping, self.identity),
            'from_concept': mapping.from_concept_code or get(mapping.from_concept, 'mnemonic'),
            'from_source': mapping.from_source_url,
            'to_concept': mapping.to_concept_code or get(mapping.to_concept, 'mnemonic'),
            'to_source': mapping.to_source_url,
            'map_type': mapping.map_type,
        }

    def process(self):  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        from core.mappings.models import Mapping
        from core.concepts.models import Concept
        concepts_result = {}
        mappings_result = {}
        traversed_mappings = set()
        traversed_concepts = set()
        ignored_diffs = ['same', 'smart_same']
        for key, diff in self.concepts_diff.result.items():  # pylint: disable=too-many-nested-blocks
            if key in ignored_diffs:
                continue
            if isinstance(diff, dict):
                section_summary = {}
                for concept_id in diff[self.identity]:
                    if concept_id in traversed_concepts:
                        continue
                    traversed_concepts.add(concept_id)
                    concept_db_id = self.concepts_diff.get_db_id_for(key, concept_id)
                    concept = Concept.objects.filter(id=concept_db_id).first()
                    summary = {'id': concept_id, 'display_name': concept.display_name}
                    mappings_diff_summary = {}
                    for mapping_diff_key in self.mappings_diff.result:
                        if mapping_diff_key in ignored_diffs:
                            continue
                        mapping_ids = get(self.mappings_diff.result, f'{mapping_diff_key}.{self.identity}')
                        if mapping_ids:
                            mappings = Mapping.objects.filter(
                                from_concept__versioned_object_id=concept.versioned_object_id,
                                **{f'{self.identity}__in': set(mapping_ids) - traversed_mappings}
                            )
                            for mapping in mappings:
                                if mapping_diff_key not in mappings_diff_summary:
                                    mappings_diff_summary[mapping_diff_key] = []
                                mappings_diff_summary[mapping_diff_key].append(self.get_mapping_summary(mapping))
                                traversed_mappings.add(get(mapping, self.identity))
                    if mappings_diff_summary:
                        summary['mappings'] = mappings_diff_summary
                    section_summary[concept_id] = summary
                if section_summary:
                    concepts_result[key] = section_summary
        same_concept_ids = self.concepts_diff.result['same'][self.identity]
        for key, diff in self.mappings_diff.result.items():  # pylint: disable=too-many-nested-blocks
            if key in ignored_diffs:
                continue
            if isinstance(diff, dict):
                section_summary = {}
                for mapping_id in diff[self.identity]:
                    if mapping_id in traversed_mappings:
                        continue
                    traversed_mappings.add(mapping_id)
                    mapping_db_id = self.mappings_diff.get_db_id_for(key, mapping_id)
                    mapping = Mapping.objects.filter(id=mapping_db_id).first()
                    from_concept_code = get(mapping, 'from_concept_code')
                    if from_concept_code:
                        from_concept = mapping.from_concept
                        concept_id = from_concept_code
                        if concept_id in same_concept_ids:
                            if 'same_with_mapping_changes' not in concepts_result:
                                concepts_result['same_with_mapping_changes'] = {}
                            if concept_id not in concepts_result['same_with_mapping_changes']:
                                concepts_result['same_with_mapping_changes'][concept_id] = {
                                    'id': concept_id,
                                    'display_name': get(from_concept, 'display_name'),
                                    'mappings': {}
                                }
                            if key not in concepts_result['same_with_mapping_changes'][concept_id]['mappings']:
                                concepts_result['same_with_mapping_changes'][concept_id]['mappings'][key] = []
                            concepts_result['same_with_mapping_changes'][concept_id]['mappings'][key].append(
                                self.get_mapping_summary(mapping, mapping_id))
                    else:
                        section_summary[mapping_id] = self.get_mapping_summary(mapping, mapping_id)
                if section_summary:
                    mappings_result[key] = section_summary
        self.result = {
            'concepts': concepts_result,
            'mappings': mappings_result,
        }
