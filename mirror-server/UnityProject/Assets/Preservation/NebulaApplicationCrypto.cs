using System;
using System.Security.Cryptography;
using System.Text;

namespace NebulaPreservation
{
    // Client native AES ctor0x6a35a0, Encrypt0x6a32c0, Decrypt0x6a2f80.
    // Server replies do not append the CLIENT platform-name trailer.
    public static class NebulaApplicationCrypto
    {
        private static readonly byte[] Key = MakeKey();

        private static byte[] MakeKey()
        {
            using (SHA1 sha = SHA1.Create())
            {
                byte[] digest = sha.ComputeHash(Encoding.UTF8.GetBytes("a56Bhg2Fbg789Lmk"));
                var key = new byte[16];
                Buffer.BlockCopy(digest, 0, key, 0, key.Length);
                return key;
            }
        }

        public static string EncryptReply(string plaintext)
        {
            if (plaintext == null) throw new ArgumentNullException(nameof(plaintext));
            using (Aes aes = Aes.Create())
            {
                aes.Key = Key;
                aes.Mode = CipherMode.ECB;
                aes.Padding = PaddingMode.PKCS7;
                byte[] bytes = Encoding.UTF8.GetBytes(plaintext);
                using (ICryptoTransform transform = aes.CreateEncryptor())
                    return Convert.ToBase64String(transform.TransformFinalBlock(bytes, 0, bytes.Length));
            }
        }

        public static string DecryptClient(string ciphertext)
        {
            if (String.IsNullOrEmpty(ciphertext) || ciphertext.Length > 65532 || ciphertext.Length % 4 != 0)
                throw new ArgumentException("invalid_ciphertext_length");
            // Native IsBase64 rejects whitespace before decoding.
            foreach (char c in ciphertext)
                if (c == ' ' || c == '\t' || c == '\r' || c == '\n')
                    throw new ArgumentException("invalid_ciphertext_whitespace");
            byte[] bytes = Convert.FromBase64String(ciphertext);
            using (Aes aes = Aes.Create())
            {
                aes.Key = Key;
                aes.Mode = CipherMode.ECB;
                aes.Padding = PaddingMode.PKCS7;
                using (ICryptoTransform transform = aes.CreateDecryptor())
                    return new UTF8Encoding(false, true).GetString(transform.TransformFinalBlock(bytes, 0, bytes.Length));
            }
        }
    }
}
