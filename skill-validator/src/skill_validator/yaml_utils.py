import yaml


class UniqueKeyLoader(yaml.SafeLoader):
    """YAML seguro: não aceita chaves duplicadas nem aliases/merges."""

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise ValueError("Aliases YAML não são suportados neste demo.")
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise ValueError("As chaves YAML devem ser strings.")
            if key in mapping:
                raise ValueError("Chave YAML duplicada.")
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def load_yaml(text: str):
    return yaml.load(text, Loader=UniqueKeyLoader)
