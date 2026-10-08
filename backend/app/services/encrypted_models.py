"""Encrypt ORM content at flush, binding it to its row and owner.

Properties keep caller assignments usable before flush. Loaded raw columns are
never silently interpreted as plaintext; legacy imports must be explicit.
"""

from sqlalchemy import event


def encrypted_property(column, field, *, json_value=False, default=None):
    pending = f"{column}_pending"

    def get(instance):
        if pending in instance.__dict__:
            return instance.__dict__[pending]
        stored = getattr(instance, column)
        if stored is None:
            return default() if callable(default) else default
        from app.services.data_crypto import get_crypto
        decrypt = get_crypto().decrypt_json if json_value else get_crypto().decrypt_text
        return decrypt(stored, owner=instance.crypto_owner, record=instance.crypto_record, field=field)

    def set_value(instance, value):
        instance.__dict__[pending] = value
        # Make SQLAlchemy include the object in its flush. before_insert/update
        # replaces this in-memory value before any INSERT/UPDATE reaches SQL.
        setattr(instance, column, value)

    return property(get, set_value)


def register_encrypted_model(model, fields):
    def seal(_mapper, _connection, instance):
        from app.services.data_crypto import get_crypto
        crypto = get_crypto()
        for column, field, json_value, default in fields:
            pending = f"{column}_pending"
            if pending not in instance.__dict__:
                if getattr(instance, column) is not None:
                    continue
                value = default() if callable(default) else default
            else:
                value = instance.__dict__[pending]
            encrypt = crypto.encrypt_json if json_value else crypto.encrypt_text
            setattr(instance, column, encrypt(value, owner=instance.crypto_owner,
                                              record=instance.crypto_record, field=field))
            instance.__dict__.pop(pending, None)

    event.listen(model, "before_insert", seal)
    event.listen(model, "before_update", seal)
